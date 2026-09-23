from ..tasks import build_family, case as c

REFERENCE = {
"intervals.py": '''
def interval(row):
    start, end = row["start"], row["end"]
    if type(start) is not int or type(end) is not int or start >= end:
        raise ValueError("invalid half-open interval")
    return [start, end]

def overlaps(left, right):
    return left[0] < right[1] and right[0] < left[1]

def merge(rows):
    result = []
    for start, end in sorted(rows):
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result

def gaps(window, busy, duration):
    if type(duration) is not int or duration <= 0:
        raise ValueError("duration must be positive")
    cursor, end = window
    result = []
    clipped = [[max(cursor,s),min(end,e)] for s,e in busy if s < end and e > cursor]
    for start, stop in merge(clipped):
        if start - cursor >= duration:
            result.append([cursor, start])
        cursor = max(cursor, stop)
    if end - cursor >= duration:
        result.append([cursor, end])
    return result
''',
"calendar.py": '''
from intervals import interval, overlaps, gaps

def active(rows, resource):
    result = []
    for row in rows:
        if row.get("status", "confirmed") == "cancelled":
            continue
        if row.get("resource", "default") != resource:
            continue
        result.append((row["id"], interval(row)))
    return result

def conflicts(candidate, rows):
    target = interval(candidate)
    return sorted(identifier for identifier, slot in active(rows, candidate.get("resource", "default"))
                  if identifier != candidate.get("id") and overlaps(target, slot))

def availability(request):
    window = interval(request["window"])
    busy = [slot for _,slot in active(request.get("bookings", []), request.get("resource", "default"))]
    return gaps(window, busy, request.get("duration", 1))
''',
"service.py": '''
from calendar import conflicts, availability

def run(request):
    if request.get("op", "conflicts") == "free":
        return availability(request)
    return conflicts(request["candidate"], request.get("bookings", []))
'''}
SPEC="A deterministic room scheduler uses integer minutes and half-open [start,end) intervals (negative minutes allowed). Intervals must have strict integer endpoints and start<end. Conflict checks ignore cancelled bookings, other resources and the candidate's own id; results are sorted ids. Default resource is 'default', default status confirmed. Free availability clips bookings to a window, merges overlapping/touching busy intervals and returns maximal free intervals at least duration minutes (strict positive integer). Validate only relevant active booking intervals. Input bookings need not be sorted."
B=lambda id,s,e,**kw: {"id":id,"start":s,"end":e,**kw}
F=lambda s,e,bookings,**kw: {"op":"free","window":{"start":s,"end":e},"bookings":bookings,**kw}
C=lambda s,e,bookings,**kw: {"candidate":{"start":s,"end":e,**kw},"bookings":bookings}
EDGE=("intervals.py","left[0] < right[1] and right[0] < left[1]","left[0] <= right[1] and right[0] <= left[1]")
MERGE=("intervals.py","result[-1][1] = max(result[-1][1], end)","result[-1][1] = end")
TAIL=("intervals.py","if end - cursor >= duration:","if end - cursor > duration:")
STATUS=("calendar.py",'if row.get("status", "confirmed") == "cancelled":','if False:')
RESOURCE=("calendar.py",'if row.get("resource", "default") != resource:','if False:')
INVALID=("intervals.py","type(start) is not int or type(end) is not int or start >= end","type(start) is not int or type(end) is not int or start > end")

def tasks():
 return build_family("scheduling","train",REFERENCE,SPEC,[
  dict(slug="adjacent-bookings",title="Respect half-open booking boundaries",category="bug_fix",summary="Adjacent appointments incorrectly conflict.",instructions="Repair overlap semantics while preserving exact-match and self-edit checks.",mutations=[EDGE],public=[c("adjacent",C(10,20,[B("a",0,10)]),[]),c("same",C(10,20,[B("a",10,20)]),["a"])],hidden=[c("right adjacent",C(0,10,[B("a",10,20)]),[]),c("containment",C(5,7,[B("a",0,10)]),["a"]),c("self edit",C(0,10,[B("a",0,10)],id="a"),[]),c("negative",C(-5,0,[B("a",-10,-5)]),[])]),
  dict(slug="availability-union",title="Compute free windows from nested bookings",category="feature",summary="Nested busy intervals expose time that remains occupied.",instructions="Complete interval union and include a tail gap exactly matching requested duration.",mutations=[MERGE,TAIL],public=[c("nested",F(0,30,[B("a",5,25),B("b",10,15)]),[[0,5],[25,30]]),c("exact tail",F(0,10,[B("a",0,5)],duration=5),[[5,10]])],hidden=[c("clip",F(0,10,[B("a",-5,3),B("b",8,20)]),[[3,8]]),c("touch",F(0,10,[B("b",5,7),B("a",2,5)]),[[0,2],[7,10]]),c("full",F(0,10,[B("a",-1,11)]),[]),c("empty",F(0,10,[],duration=10),[[0,10]])]),
  dict(slug="resource-scope",title="Restore booking scope across two APIs",category="multi_file",summary="Cancelled and unrelated room bookings leak into availability.",instructions="Repair scoped booking selection and half-open overlap across conflicts and free-window APIs.",mutations=[STATUS,RESOURCE,EDGE],public=[c("cancelled",C(5,10,[B("a",0,20,status="cancelled")]),[]),c("other room",F(0,10,[B("a",0,10,resource="B")],resource="A"),[[0,10]])],hidden=[c("same room",C(0,10,[B("a",1,2,resource="A")],resource="A"),["a"]),c("default",C(0,10,[B("a",1,2)]),["a"]),c("irrelevant malformed",C(0,10,[B("a",5,1,status="cancelled")]),[]),c("adjacent relevant",C(0,5,[B("a",5,10)]),[])]),
  dict(slug="reject-empty-slots",title="Reject zero-width calendar intervals",category="failing_tests",summary="A zero-minute appointment is accepted by both scheduler facades.",instructions="Restore the strict interval invariant for candidates and free windows without rejecting negative timestamps.",mutations=[INVALID],public=[c("empty candidate",C(5,5,[]),error="ValueError"),c("empty window",F(0,0,[]),error="ValueError")],hidden=[c("negative",F(-10,-5,[]),[[-10,-5]]),c("reverse",C(9,8,[]),error="ValueError"),c("bool",C(False,10,[]),error="ValueError"),c("zero duration",F(0,10,[],duration=0),error="ValueError")]),
  dict(slug="calendar-recovery",title="Recover a room-calendar migration",category="long_horizon",difficulty="hard",summary="Room scoping, endpoint semantics and union logic regressed together.",instructions="Restore resource/status filtering, half-open conflicts, nested interval union, inclusive minimum-gap boundaries and interval validation across modules. This is an integrated miniature stress task.",mutations=[EDGE,MERGE,TAIL,STATUS,RESOURCE,INVALID],public=[c("integrated free",F(0,30,[B("a",5,25),B("b",10,15),B("c",0,30,status="cancelled")],duration=5),[[0,5],[25,30]]),c("room boundary",C(0,5,[B("a",5,10),B("b",0,10,resource="B")]),[])],hidden=[c("invalid",F(5,5,[]),error="ValueError"),c("overlap",C(5,9,[B("b",8,10),B("a",0,6)]),["a","b"]),c("off window",F(0,10,[B("a",20,30)]),[[0,10]]),c("clipped",F(0,10,[B("a",-5,4),B("b",2,3)],duration=6),[[4,10]]),c("no bookings",C(0,2,[]),[])]),
 ])
