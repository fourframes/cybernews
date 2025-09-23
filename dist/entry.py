import json
from js import Response, console

async def fetch(request, env):
    url = request.url
    if url.endswith("/test-run"):
        console.log("Manual test run triggered")
        return Response.new("Test run executed", status=200)
    return Response.new("OK", status=200)

default = {
    "fetch": fetch
}
