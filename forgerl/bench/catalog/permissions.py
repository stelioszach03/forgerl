from ..tasks import build_family, case as c

REFERENCE={
"roles.py": '''
def expand(name, roles, trail):
    if name in trail:
        raise ValueError("role inheritance cycle")
    if name not in roles:
        raise ValueError("unknown role")
    row = roles[name]
    result = list(row.get("rules", []))
    for parent in row.get("inherits", []):
        result += expand(parent, roles, trail + [name])
    return result

def rules_for(actor, roles):
    result = []
    for name in actor.get("roles", []):
        result += expand(name, roles, [])
    return result
''',
"policy.py": '''
def matches(pattern, resource):
    left, right = pattern.split("/"), resource.split("/")
    return len(left) == len(right) and all(a == "*" or a == b for a,b in zip(left,right))

def authorize(rules, action, resource):
    relevant = [row for row in rules if row["action"] in (action, "*") and matches(row["resource"], resource)]
    if any(row["effect"] == "deny" for row in relevant):
        return False
    return any(row["effect"] == "allow" for row in relevant)

def project(record, fields):
    forbidden = {"password", "token"}
    return {key: value for key,value in record.items() if key in fields and key not in forbidden}
''',
"service.py": '''
from roles import rules_for
from policy import authorize, project

def run(request):
    actor = request["actor"]
    rules = rules_for(actor, request.get("roles", {}))
    if request.get("op", "check") == "check":
        return authorize(rules, request["action"], request["resource"])
    if request.get("op") == "batch":
        return [authorize(rules, item["action"], item["resource"]) for item in request["checks"]]
    result = []
    for record in request.get("records", []):
        if record.get("tenant") != actor.get("tenant"):
            continue
        if authorize(rules, "read", "records/" + record["id"]):
            result.append(project(record, actor.get("fields", [])))
    return result
'''}
SPEC="An in-memory authorization service expands each actor role through inherits, rejecting missing roles and cycles (including cycles with rules). A rule has action, resource and effect allow/deny. Resource patterns are slash-separated; '*' matches exactly one segment, never an arbitrary suffix; actions support '*'. Any matching deny overrides all allows; no match denies. op=check returns bool, batch applies the same policy. op=export preserves input record order, permits only equal actor/record tenant and read authorization at records/{id}, then includes only actor.fields; password and token are always excluded. This is a logic exercise, not a production authentication system."
RULE=lambda effect="allow",resource="records/*",action="read":{"effect":effect,"resource":resource,"action":action}
REQ=lambda rules,**kw:{"actor":{"roles":["member"],"tenant":"A","fields":["id","name"]},"roles":{"member":{"rules":rules}},"action":"read","resource":"records/one",**kw}
DENY=("policy.py",'if any(row["effect"] == "deny" for row in relevant):','if False:')
WILD=("policy.py",'len(left) == len(right) and all(a == "*" or a == b for a,b in zip(left,right))','all(a == "*" or a == b for a,b in zip(left,right))')
INHERIT=("roles.py",'result += expand(parent, roles, trail + [name])','result += []')
SECRET=("policy.py",'and key not in forbidden','')
TENANT=("service.py",'if record.get("tenant") != actor.get("tenant"):','if False:')

def tasks():
 return build_family("permissions","train",REFERENCE,SPEC,[
  dict(slug="deny-precedence",title="Enforce deny precedence in policy evaluation",category="bug_fix",summary="A broad allow bypasses a narrower explicit denial.",instructions="Make matching deny rules override allows in single and batch checks.",mutations=[DENY],public=[c("deny wins",REQ([RULE(),RULE("deny","records/one")]),False),c("batch",REQ([RULE(),RULE("deny","records/private")],op="batch",checks=[{"action":"read","resource":"records/private"},{"action":"read","resource":"records/public"}]),[False,True])],hidden=[c("deny alone",REQ([RULE("deny")]),False),c("unrelated deny",REQ([RULE(),RULE("deny","images/*")]),True),c("action mismatch",REQ([RULE()],action="write"),False),c("no roles",{"actor":{"roles":[]},"action":"read","resource":"records/a"},False)]),
  dict(slug="segment-wildcards",title="Implement exact-depth resource wildcards",category="feature",summary="Prefix matching grants unintended deeper resources.",instructions="Require equal segment counts while allowing wildcards in any individual segment.",mutations=[WILD],public=[c("too deep",REQ([RULE()],resource="records/a/private"),False),c("too short",REQ([RULE()],resource="records"),False)],hidden=[c("normal",REQ([RULE()],resource="records/a"),True),c("middle wildcard",REQ([RULE(resource="teams/*/records")],resource="teams/A/records"),True),c("literal",REQ([RULE(resource="records/a")],resource="records/b"),False),c("action wildcard",REQ([RULE(action="*")],action="delete"),True)]),
  dict(slug="role-inheritance",title="Resolve inherited roles with cycle checks",category="failing_tests",summary="Inherited permissions disappeared during role loading.",instructions="Restore recursive inheritance, including transitive denies and errors for missing/cyclic roles.",mutations=[INHERIT],public=[c("parent",{"actor":{"roles":["child"]},"roles":{"child":{"inherits":["base"]},"base":{"rules":[RULE()]}},"action":"read","resource":"records/a"},True),c("cycle",{"actor":{"roles":["a"]},"roles":{"a":{"inherits":["b"]},"b":{"inherits":["a"]}},"action":"read","resource":"records/a"},error="ValueError")],hidden=[c("missing parent",{"actor":{"roles":["a"]},"roles":{"a":{"inherits":["missing"]}},"action":"read","resource":"x"},error="ValueError"),c("transitive",{"actor":{"roles":["c"]},"roles":{"c":{"inherits":["b"]},"b":{"inherits":["a"]},"a":{"rules":[RULE()]}},"action":"read","resource":"records/a"},True),c("inherited deny",{"actor":{"roles":["c"]},"roles":{"c":{"rules":[RULE()],"inherits":["b"]},"b":{"rules":[RULE("deny")]}},"action":"read","resource":"records/a"},False),c("plain",REQ([RULE()]),True)]),
  dict(slug="safe-export",title="Align tenant filtering and field projection",category="multi_file",summary="Export combines another tenant's rows with secret fields.",instructions="Restore tenant filtering in the export facade and deny secret fields in projection even when explicitly requested.",mutations=[TENANT,SECRET],public=[c("tenant",REQ([RULE()],op="export",records=[{"id":"a","tenant":"B","name":"Other"}]),[]),c("secrets",REQ([RULE()],op="export",actor={"roles":["member"],"tenant":"A","fields":["id","token"]},records=[{"id":"a","tenant":"A","token":"secret"}]),[{"id":"a"}])],hidden=[c("allowed",REQ([RULE()],op="export",records=[{"id":"a","tenant":"A","name":"Anna","extra":2}]),[{"id":"a","name":"Anna"}]),c("denied",REQ([RULE("deny")],op="export",records=[{"id":"a","tenant":"A"}]),[]),c("password",REQ([RULE()],op="export",actor={"roles":["member"],"tenant":"A","fields":["password"]},records=[{"id":"a","tenant":"A","password":"secret"}]),[{}]),c("empty",REQ([RULE()],op="export",records=[]),[])]),
  dict(slug="policy-migration",title="Recover a multi-tenant access-policy migration",category="long_horizon",difficulty="hard",summary="Inheritance, denial, scope and projection require coordinated recovery.",instructions="Repair role inheritance, explicit-deny precedence, exact-depth wildcard matching, tenant isolation and secret projection together. Miniature multi-requirement stress task.",mutations=[DENY,WILD,INHERIT,TENANT,SECRET],public=[c("inherited scoped export",{"op":"export","actor":{"roles":["child"],"tenant":"A","fields":["id","token"]},"roles":{"child":{"inherits":["base"],"rules":[RULE("deny","records/private")]},"base":{"rules":[RULE()]}},"records":[{"id":"public","tenant":"A","token":"x"},{"id":"private","tenant":"A"},{"id":"other","tenant":"B"}]},[{"id":"public"}]),c("wildcard depth",REQ([RULE()],resource="records/a/extra"),False)],hidden=[c("cycle",{"actor":{"roles":["a"]},"roles":{"a":{"inherits":["a"]}},"action":"read","resource":"x"},error="ValueError"),c("deny",REQ([RULE(),RULE("deny")]),False),c("valid",REQ([RULE()]),True),c("missing",{"actor":{"roles":["x"]},"action":"read","resource":"x"},error="ValueError"),c("safe fields",REQ([RULE()],op="export",records=[{"id":"a","tenant":"A","name":"N","token":"x"}]),[{"id":"a","name":"N"}])]),
 ])
