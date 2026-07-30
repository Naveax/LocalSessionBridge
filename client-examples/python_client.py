import os
import urllib.request

name = "hubspot-a"
token = os.environ["ULSB_API_TOKEN"]
request = urllib.request.Request(
    f"http://127.0.0.1:17871/v1/sessions/{name}/cookie-header",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(request, timeout=10) as response:
    print(response.read().decode("utf-8"))
