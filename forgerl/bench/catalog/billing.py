from ..tasks import build_family, case as c

REFERENCE = {
"money.py": '''
def amount(value):
    if type(value) is not int or value < 0:
        raise ValueError("money must be nonnegative integer cents")
    return value

def round_ratio(value, numerator, denominator):
    return (value * numerator + denominator // 2) // denominator

def discount(subtotal, coupons):
    seen = set()
    result = 0
    for coupon in coupons:
        code = coupon["code"]
        if code in seen:
            continue
        seen.add(code)
        result += amount(coupon["cents"])
    return min(subtotal, result)
''',
"invoice.py": '''
from money import amount, round_ratio, discount

def line_total(line):
    quantity = line["quantity"]
    if type(quantity) is not int or quantity < 0:
        raise ValueError("quantity must be a nonnegative integer")
    return amount(line["unit_cents"]) * quantity

def quote(request):
    lines = [line_total(line) for line in request.get("lines", [])]
    subtotal = sum(lines)
    reduction = discount(subtotal, request.get("coupons", []))
    taxable = subtotal - reduction
    rate = request.get("tax_bps", 0)
    if type(rate) is not int or not 0 <= rate <= 10000:
        raise ValueError("tax_bps out of range")
    tax = round_ratio(taxable, rate, 10000)
    credit = amount(request.get("credit_cents", 0))
    return {"subtotal": subtotal, "discount": reduction, "tax": tax,
            "total": max(0, taxable + tax - credit)}
''',
"service.py": '''
from invoice import quote, line_total
from money import amount

def run(request):
    if request.get("op", "quote") == "line":
        return line_total(request["line"])
    if request.get("op") == "validate":
        return amount(request["value"])
    return quote(request)
'''}
SPEC = "A billing service operates exclusively in integer cents. quote accepts lines (unit_cents, quantity), optional coupons (code,cents), tax_bps and credit_cents. Nonnegative integer money/quantity values reject booleans. Coupon codes are idempotent: the first occurrence wins; sum discounts then cap at subtotal. Tax is rounded half-up on the discounted subtotal, in basis points 0..10000; deduct credit after tax and clamp total at zero. Empty lines are valid. op=line exposes identical line validation; op=validate exposes money validation. Preserve both facades. No external currency/rate lookup."
Q = lambda n, **kw: {"lines": [{"unit_cents": n, "quantity": 1}], **kw}
R = lambda subtotal, discount=0, tax=0, total=None: {"subtotal": subtotal, "discount": discount, "tax": tax, "total": subtotal-discount+tax if total is None else total}
CREDIT = ("invoice.py", "taxable + tax - credit", "taxable + tax + credit")
TAX = ("money.py", "return (value * numerator + denominator // 2) // denominator", "return value * numerator // denominator")
VALID = ("money.py", "type(value) is not int or value < 0", "not isinstance(value, int) or value < 0")
QUANTITY = ("invoice.py", "type(quantity) is not int or quantity < 0", "not isinstance(quantity, int) or quantity < 0")
COUPON = ("money.py", "if code in seen:", "if False:")

def tasks():
    return build_family("billing", "train", REFERENCE, SPEC, [
        dict(slug="credit-order", title="Apply account credit after tax", category="bug_fix", summary="A checkout refund credit increases the amount due.", instructions="Repair the credit arithmetic and keep tax independent of credits.", mutations=[CREDIT], public=[c("credit",Q(1000,credit_cents=200),R(1000,total=800)),c("tax before credit",Q(1000,tax_bps=1000,credit_cents=500),R(1000,tax=100,total=600))], hidden=[c("over-credit",Q(30,credit_cents=60),R(30,total=0)),c("zero",Q(0),R(0)),c("coupon",Q(100,coupons=[{"code":"x","cents":10}],credit_cents=20),R(100,10,total=70)),c("invalid credit",Q(100,credit_cents=-1),error="ValueError")]),
        dict(slug="tax-rounding", title="Implement half-up tax rounding", category="feature", summary="Tax truncation loses cents at half-unit boundaries.", instructions="Implement exact half-up ratio rounding without floating-point drift.", mutations=[TAX], public=[c("half cent",Q(1,tax_bps=5000),R(1,tax=1)),c("discounted basis",Q(105,tax_bps=1000,coupons=[{"code":"x","cents":10}]),R(105,10,10))], hidden=[c("below half",Q(1,tax_bps=4999),R(1)),c("above half",Q(3,tax_bps=5000),R(3,tax=2)),c("large exact",Q(100000001,tax_bps=5000),R(100000001,tax=50000001)),c("bad rate",Q(1,tax_bps=10001),error="ValueError")]),
        dict(slug="shared-validation", title="Unify validation across billing facades", category="refactor", summary="Legacy facade validators accept booleans as money and quantities.", instructions="Refactor validation consistently across quote, line and validate entrypoints. Boolean values must be rejected; preserve valid integer behavior. Behavioral tests do not mandate a particular helper layout.", mutations=[VALID,QUANTITY], public=[c("money bool",{"op":"validate","value":True},error="ValueError"),c("quantity bool",{"op":"line","line":{"unit_cents":10,"quantity":True}},error="ValueError")], hidden=[c("quote money bool",Q(True),error="ValueError"),c("float money",Q(1.5),error="ValueError"),c("zero quantity",{"op":"line","line":{"unit_cents":20,"quantity":0}},0),c("normal line",{"op":"line","line":{"unit_cents":7,"quantity":3}},21)]),
        dict(slug="coupon-idempotency", title="Make coupon replay idempotent", category="failing_tests", summary="Retrying a coupon submission applies the same code twice.", instructions="Fix the failing duplicate-code tests. Preserve first-write semantics and validate only the accepted coupon amount.", mutations=[COUPON], public=[c("duplicate",Q(100,coupons=[{"code":"x","cents":10},{"code":"x","cents":10}]),R(100,10)),c("first wins",Q(100,coupons=[{"code":"x","cents":5},{"code":"x","cents":90}]),R(100,5))], hidden=[c("two codes",Q(100,coupons=[{"code":"x","cents":10},{"code":"y","cents":20}]),R(100,30)),c("cap",Q(5,coupons=[{"code":"x","cents":10}]),R(5,5)),c("ignored repeat",Q(20,coupons=[{"code":"x","cents":2},{"code":"x","cents":-1}]),R(20,2)),c("none",Q(12),R(12))]),
        dict(slug="checkout-recovery", title="Recover an integrated checkout pipeline", category="long_horizon", difficulty="hard", summary="A miniature checkout upgrade regresses coupons, tax, credits and validation.", instructions="Repair four interacting stages across money.py and invoice.py: replay-safe coupons, exact tax rounding, post-tax credit and strict integer validation. This is a miniature multi-requirement stress task.", mutations=[CREDIT,TAX,VALID,QUANTITY,COUPON], public=[c("combined",Q(105,tax_bps=1000,credit_cents=20,coupons=[{"code":"x","cents":10},{"code":"x","cents":10}]),R(105,10,10,total=85)),c("strict",{"op":"line","line":{"unit_cents":1,"quantity":True}},error="ValueError")], hidden=[c("round cap",Q(1,tax_bps=5000,credit_cents=9),R(1,tax=1,total=0)),c("coupon cap",Q(5,coupons=[{"code":"x","cents":9}]),R(5,5)),c("bool credit",Q(10,credit_cents=False),error="ValueError"),c("empty",{},R(0)),c("multi line",{"lines":[{"unit_cents":11,"quantity":3},{"unit_cents":7,"quantity":2}],"tax_bps":1000},R(47,tax=5))]),
    ])
