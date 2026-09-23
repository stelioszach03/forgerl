from ..tasks import build_family, case as c

REFERENCE={
"events.py": '''
def cleaned(rows):
    seen, result = set(), []
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        if type(row["at"]) is not int or type(row["value"]) not in (int, float):
            raise ValueError("invalid event")
        result.append(dict(row))
    return result

def window(rows, start, end):
    if type(start) is not int or type(end) is not int or start >= end:
        raise ValueError("invalid window")
    return [row for row in rows if start <= row["at"] < end]
''',
"metrics.py": '''
def summarize(rows):
    groups = {}
    for row in rows:
        key = row.get("group", "unknown")
        groups.setdefault(key, []).append(row["value"])
    return {key: {"count": len(values), "sum": sum(values), "mean": sum(values) / len(values)}
            for key, values in sorted(groups.items())}

def buckets(rows, start, end, width):
    if type(width) is not int or width <= 0:
        raise ValueError("invalid bucket width")
    result = []
    cursor = start
    while cursor < end:
        stop = min(end, cursor + width)
        values = [row["value"] for row in rows if cursor <= row["at"] < stop]
        result.append({"start": cursor, "end": stop, "count": len(values), "sum": sum(values)})
        cursor = stop
    return result

def quantile(values, q):
    if type(q) not in (int, float) or not 0 <= q <= 1:
        raise ValueError("invalid quantile")
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
''',
"service.py": '''
from events import cleaned, window
from metrics import summarize, buckets, quantile

def run(request):
    rows = window(cleaned(request.get("events", [])), request["start"], request["end"])
    if request.get("op") == "buckets":
        return buckets(rows, request["start"], request["end"], request["width"])
    if request.get("op") == "quantile":
        return quantile([row["value"] for row in rows], request["q"])
    return summarize(rows)
'''}
SPEC="A bounded analytics pipeline first deduplicates event ids by first occurrence, then validates integer timestamps and numeric int/float values (booleans rejected), then filters [start,end). start/end are strict integers with start<end. Group summary returns count,sum,arithmetic mean; missing group='unknown'. op=buckets emits every window anchored at start, including empty and final partial buckets, using positive integer width. op=quantile uses linear interpolation at (n-1)*q for q in[0,1], returns null for no rows. Quantile validation precedes empty handling. Inputs are finite JSON numbers."
E=lambda id,t,v,g="g":{"id":id,"at":t,"value":v,"group":g}
Q=lambda rows,**kw:{"events":rows,"start":0,"end":10,**kw}
S=lambda count,total:{"count":count,"sum":total,"mean":total/count}
B=lambda start,end,count,total:{"start":start,"end":end,"count":count,"sum":total}
BOUND=("events.py",'start <= row["at"] < end','start <= row["at"] <= end')
DEDUP=("events.py",'if row["id"] in seen:','if False:')
MEAN=("metrics.py",'"mean": sum(values) / len(values)','"mean": sum(values) // len(values)')
PARTIAL=("metrics.py",'while cursor < end:','while cursor + width <= end:')
QUANT=("metrics.py",'(len(ordered) - 1) * q','len(ordered) * q')

def tasks():
 return build_family("analytics","validation",REFERENCE,SPEC,[
  dict(slug="window-boundary",title="Prevent double-counting adjacent reporting windows",category="bug_fix",summary="The end boundary belongs to two neighboring reports.",instructions="Make reporting windows half-open for summaries, quantiles and buckets.",mutations=[BOUND],public=[c("exclude end",Q([E("a",10,8)]),{}),c("include start",Q([E("a",0,3)]),{"g":S(1,3)})],hidden=[c("both",Q([E("a",9,2),E("b",10,4)]),{"g":S(1,2)}),c("negative",Q([E("a",-1,3)],start=-2,end=0),{"g":S(1,3)}),c("empty",Q([]),{}),c("bad window",Q([],start=1,end=1),error="ValueError")]),
  dict(slug="partial-buckets",title="Include the final partial reporting bucket",category="feature",summary="A non-divisible reporting interval silently loses its tail.",instructions="Emit empty buckets and the final partial bucket without shifting the start anchor.",mutations=[PARTIAL],public=[c("partial",Q([E("a",9,4)],op="buckets",width=6),[B(0,6,0,0),B(6,10,1,4)]),c("wide",Q([E("a",2,1)],op="buckets",width=20),[B(0,10,1,1)])],hidden=[c("exact",Q([],op="buckets",width=5),[B(0,5,0,0),B(5,10,0,0)]),c("boundary",Q([E("a",3,1),E("b",6,2)],op="buckets",width=3),[B(0,3,0,0),B(3,6,1,1),B(6,9,1,2),B(9,10,0,0)]),c("negative origin",Q([],op="buckets",width=3,start=-2,end=2),[B(-2,1,0,0),B(1,2,0,0)]),c("bad width",Q([],op="buckets",width=0),error="ValueError")]),
  dict(slug="deduplicated-means",title="Align ingestion and fractional aggregations",category="multi_file",summary="Event retries and floor division skew reported means.",instructions="Deduplicate ids before validation and compute true arithmetic means, including negative and fractional values.",mutations=[DEDUP,MEAN],public=[c("duplicates",Q([E("a",1,1),E("a",1,1),E("b",2,4)]),{"g":S(2,5)}),c("fraction",Q([E("a",1,-1),E("b",2,0)]),{"g":S(2,-1)})],hidden=[c("first wins",Q([E("a",1,2),E("a",2,100)]),{"g":S(1,2)}),c("groups",Q([E("a",1,1,"A"),E("b",2,3,"B")]),{"A":S(1,1),"B":S(1,3)}),c("ignored invalid",Q([E("a",1,2),E("a",False,True)]),{"g":S(1,2)}),c("float",Q([E("a",1,1.5),E("b",2,2.5)]),{"g":S(2,4.0)})]),
  dict(slug="quantile-index",title="Repair endpoint-safe interpolated quantiles",category="failing_tests",summary="Quantiles interpolate at n*q and can read beyond the data.",instructions="Use the specified(n-1)*q interpolation and preserve singleton/empty behavior.",mutations=[QUANT],public=[c("median",Q([E("a",1,0),E("b",2,10)],op="quantile",q=0.5),5.0),c("max",Q([E("a",1,2)],op="quantile",q=1),2.0)],hidden=[c("min",Q([E("a",1,8),E("b",2,2)],op="quantile",q=0),2.0),c("quarter",Q([E("a",1,0),E("b",2,8),E("c",3,12)],op="quantile",q=.25),4.0),c("empty",Q([],op="quantile",q=.5),None),c("bad q",Q([],op="quantile",q=2),error="ValueError")]),
  dict(slug="reporting-recovery",title="Recover a consistent reporting pipeline",category="long_horizon",difficulty="hard",summary="Windowing, retries, means, quantiles and buckets disagree.",instructions="Repair deduplication, half-open windows, exact means, partial buckets and quantile indexing across the pipeline. Miniature integrated stress task.",mutations=[BOUND,DEDUP,MEAN,PARTIAL,QUANT],public=[c("combined summary",Q([E("a",0,1),E("a",0,1),E("b",9,4),E("c",10,100)]),{"g":S(2,5)}),c("tail",Q([E("a",9,4)],op="buckets",width=6),[B(0,6,0,0),B(6,10,1,4)])],hidden=[c("quantile",Q([E("a",1,0),E("b",2,10)],op="quantile",q=.5),5.0),c("singleton",Q([E("a",1,2)],op="quantile",q=1),2.0),c("invalid value",Q([E("a",1,True)]),error="ValueError"),c("empty",Q([]),{}),c("replayed",Q([E("a",1,2),E("a",2,9)],op="buckets",width=10),[B(0,10,1,2)])]),
 ])
