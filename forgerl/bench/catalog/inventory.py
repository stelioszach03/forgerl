from ..tasks import build_family, case as c

REFERENCE={
"ledger.py": '''
def quantity(value):
    if type(value) is not int or value < 0:
        raise ValueError("quantity must be a nonnegative integer")
    return value

def replay(initial, events):
    stock = {sku: quantity(value) for sku, value in initial.items()}
    seen = set()
    for event in events:
        identifier = event["id"]
        if identifier in seen:
            continue
        seen.add(identifier)
        count = quantity(event["quantity"])
        sku = event["sku"]
        delta = count if event["kind"] == "receive" else -count
        if event["kind"] not in ("receive", "ship"):
            raise ValueError("unknown event")
        updated = stock.get(sku, 0) + delta
        if updated < 0:
            raise ValueError("negative stock")
        stock[sku] = updated
    return stock
''',
"allocation.py": '''
from ledger import quantity

def reserve(stock, orders):
    remaining = dict(stock)
    accepted, rejected = [], []
    for order in orders:
        needed = {}
        for item in order["items"]:
            sku = item["sku"]
            needed[sku] = needed.get(sku, 0) + quantity(item["quantity"])
        if all(remaining.get(sku, 0) >= count for sku, count in needed.items()):
            for sku, count in needed.items():
                remaining[sku] = remaining.get(sku, 0) - count
            accepted.append(order["id"])
        else:
            rejected.append(order["id"])
    return {"stock": remaining, "accepted": accepted, "rejected": rejected}

def replenishment(stock, targets):
    return {sku: max(0, quantity(target) - stock.get(sku, 0))
            for sku, target in sorted(targets.items())}
''',
"service.py": '''
from ledger import replay
from allocation import reserve, replenishment

def run(request):
    stock = replay(request.get("stock", {}), request.get("events", []))
    if request.get("op") == "replenish":
        return replenishment(stock, request.get("targets", {}))
    return reserve(stock, request.get("orders", []))
'''}
SPEC="Inventory is nonnegative integer quantities keyed by SKU (booleans invalid). Replay events in order; ids are idempotent with first occurrence winning, including malformed duplicates skipped before validation. receive adds, ship subtracts; reject unknown kinds and any intermediate negative stock. Orders are processed in input order. Aggregate repeated SKUs within an order, then accept/decrement all lines atomically only if all are available; rejected orders change nothing. Return stock/accepted/rejected. Empty orders are accepted. op=replenish returns each requested target's nonnegative shortfall after event replay, including zero shortfalls."
E=lambda id,sku,q,kind="receive":{"id":id,"sku":sku,"quantity":q,"kind":kind}
O=lambda id,*items:{"id":id,"items":[{"sku":s,"quantity":q} for s,q in items]}
R=lambda stock,a=[],r=[]:{"stock":stock,"accepted":a,"rejected":r}
ID=("ledger.py","if identifier in seen:","if False:")
SHIP=("ledger.py",'delta = count if event["kind"] == "receive" else -count','delta = count')
DUP=("allocation.py","needed[sku] = needed.get(sku, 0) + quantity(item[\"quantity\"])","needed[sku] = quantity(item[\"quantity\"])")
BOUND=("allocation.py","remaining.get(sku, 0) >= count","remaining.get(sku, 0) > count")
TARGET=("allocation.py","max(0, quantity(target) - stock.get(sku, 0))","max(0, quantity(target) + stock.get(sku, 0))")

def tasks():
 return build_family("inventory","train",REFERENCE,SPEC,[
  dict(slug="event-replay",title="Deduplicate warehouse event retries",category="bug_fix",summary="Delivery retries double-count received goods.",instructions="Make event replay first-write idempotent before validating a duplicate payload.",mutations=[ID],public=[c("duplicate receive",{"events":[E("a","x",4),E("a","x",4)]},R({"x":4})),c("first wins",{"events":[E("a","x",4),E("a","y",9)]},R({"x":4}))],hidden=[c("ignored malformed",{"events":[E("a","x",4),E("a","x",-1)]},R({"x":4})),c("distinct",{"events":[E("a","x",4),E("b","x",1)]},R({"x":5})),c("ship retry",{"stock":{"x":5},"events":[E("a","x",2,"ship"),E("a","x",2,"ship")]},R({"x":3})),c("empty",{},R({}))]),
  dict(slug="atomic-reservations",title="Allocate repeated SKU lines atomically",category="feature",summary="An order can reserve the same SKU twice without paying both quantities.",instructions="Aggregate order lines before stock checks and accept exact-stock allocations.",mutations=[DUP,BOUND],public=[c("aggregate rejection",{"stock":{"x":5},"orders":[O("a",("x",3),("x",3))]},R({"x":5},[],["a"])),c("exact",{"stock":{"x":5},"orders":[O("a",("x",5))]},R({"x":0},["a"]))],hidden=[c("atomic",{"stock":{"x":5,"y":0},"orders":[O("a",("x",2),("y",1)),O("b",("x",5))]},R({"x":0,"y":0},["b"],["a"])),c("sum",{"stock":{"x":6},"orders":[O("a",("x",2),("x",3))]},R({"x":1},["a"])),c("empty order",{"orders":[O("a")]},R({},["a"])),c("bad quantity",{"orders":[O("a",("x",-1))]},error="ValueError")]),
  dict(slug="stock-projection",title="Align ledger replay and replenishment",category="multi_file",summary="Shipments and target calculations both inflate projected stock.",instructions="Fix outbound ledger deltas and calculate replenishment from the resulting stock.",mutations=[SHIP,TARGET],public=[c("ship target",{"op":"replenish","stock":{"x":10},"events":[E("a","x",4,"ship")],"targets":{"x":9}},{"x":3}),c("over target",{"op":"replenish","stock":{"x":12},"targets":{"x":10}},{"x":0})],hidden=[c("missing",{"op":"replenish","targets":{"x":7}},{"x":7}),c("zero",{"op":"replenish","stock":{"x":0},"targets":{"x":0}},{"x":0}),c("negative intermediate",{"events":[E("a","x",1,"ship"),E("b","x",2)]},error="ValueError"),c("receive",{"op":"replenish","events":[E("a","x",3)],"targets":{"x":5}},{"x":2})]),
  dict(slug="shipment-regression",title="Restore outbound inventory accounting",category="failing_tests",summary="Shipping adds stock after a ledger refactor.",instructions="Restore outbound signs, unknown-kind rejection and prevention of intermediate overdrafts.",mutations=[SHIP],public=[c("ship",{"stock":{"x":7},"events":[E("a","x",3,"ship")]},R({"x":4})),c("overdraw",{"stock":{"x":1},"events":[E("a","x",2,"ship")]},error="ValueError")],hidden=[c("exact ship",{"stock":{"x":2},"events":[E("a","x",2,"ship")]},R({"x":0})),c("receive preserved",{"events":[E("a","x",2)]},R({"x":2})),c("unknown",{"events":[E("a","x",2,"adjust")]},error="ValueError"),c("bool rejected",{"stock":{"x":True}},error="ValueError")]),
  dict(slug="warehouse-recovery",title="Recover the warehouse fulfillment flow",category="long_horizon",difficulty="hard",summary="Idempotency, allocation and stock projections disagree after migration.",instructions="Repair replay deduplication, shipment signs, repeated-line aggregation, exact-stock reservations and target projections. Preserve transactional order acceptance. Miniature multi-requirement stress task.",mutations=[ID,SHIP,DUP,BOUND,TARGET],public=[c("integrated",{"stock":{"x":10},"events":[E("a","x",2,"ship"),E("a","x",2,"ship")],"orders":[O("one",("x",3),("x",5))]},R({"x":0},["one"])),c("projection",{"op":"replenish","stock":{"x":5},"events":[E("a","x",2,"ship")],"targets":{"x":8}},{"x":5})],hidden=[c("rejected unchanged",{"stock":{"x":3},"orders":[O("a",("x",2),("x",2)),O("b",("x",3))]},R({"x":0},["b"],["a"])),c("duplicate invalid",{"events":[E("a","x",1),E("a","x",-4)]},R({"x":1})),c("underflow",{"events":[E("a","x",1,"ship")]},error="ValueError"),c("baseline",{"stock":{"a":0}},R({"a":0})),c("zero shortfall",{"op":"replenish","stock":{"x":10},"targets":{"x":1}},{"x":0})]),
 ])
