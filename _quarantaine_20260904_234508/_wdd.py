import requests, itertools, time, json, sys
H = {"User-Agent":"JobHunterBelgium/1.0 (personal job search)",
     "Accept":"application/json","Content-Type":"application/json"}
TENANTS = ["jnj","takeda","ucb","pfizer","msd","novartis","astrazeneca",
           "amgen","catalent","terumo","solvay","syensqo","umicore",
           "abinbev","danone","cargill","lonza","bayer","viatris","organon"]
WD = ["wd1","wd3","wd5"]
def sites(t):
    c = t.capitalize()
    return [t, f"{c}Careers", "External"]
out = []
for t in TENANTS:
    ok = False
    for wd, site in itertools.product(WD, sites(t)):
        if ok: break
        url = f"https://{t}.{wd}.myworkdayjobs.com/wday/cxs/{t}/{site}/jobs"
        try:
            r = requests.post(url, json={"appliedFacets":{},"limit":1,"offset":0,
                              "searchText":"Belgium"}, timeout=5, headers=H)
        except Exception:
            continue
        time.sleep(0.05)
        if r.status_code == 200:
            try: d = r.json()
            except Exception: continue
            if "total" in d:
                out.append({"tenant":t,"wd":wd,"site":site,"belgium":d.get("total")})
                print(f"  {t:<14} {wd:<5} {site:<18} BE~{d.get('total')}", flush=True)
                ok = True
json.dump(out, open("/tmp/wd_found.json","w"), indent=1)
print(f"\n{len(out)} tenants trouves sur {len(TENANTS)}", flush=True)
