"""Scheduled, bounded statistical research. No external API keys or paid services."""
import json, math, random, datetime, pathlib
ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/"data"/"research.json"
OUT.parent.mkdir(exist_ok=True)
rng=random.Random()
def bernoulli(n,p):
 x=sum(rng.random()<p for _ in range(n))
 z=(x-n*p)/math.sqrt(n*p*(1-p))
 return {"observed":round(x/n,6),"expected":p,"z_score":round(z,3),"trials":n,"flag":abs(z)>3.29}
def pi_test(n):
 hits=sum(rng.random()**2+rng.random()**2<=1 for _ in range(n))
 estimate=4*hits/n
 # Standard error of four times a Bernoulli estimator.
 se=4*math.sqrt((math.pi/4)*(1-math.pi/4)/n)
 z=(estimate-math.pi)/se
 return {"observed":round(estimate,6),"expected":round(math.pi,6),"z_score":round(z,3),"trials":n,"flag":abs(z)>3.29}
tests=[
 ("Fair coin frequency",bernoulli(100000,.5)),
 ("Uniform threshold frequency",bernoulli(100000,.25)),
 ("Monte Carlo pi estimation",pi_test(100000)),
 ("Rare-event frequency",bernoulli(200000,.02)),
]
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
record={"time":now,"experiments":[{"name":name,**result} for name,result in tests],"interpretation":"Flags indicate deviations worth replication, not discoveries. Multiple-testing corrections and independent validation are required."}
try: old=json.loads(OUT.read_text())
except (FileNotFoundError,ValueError):old=[]
old.insert(0,record)
OUT.write_text(json.dumps(old[:100],indent=2)+"\n")
print(json.dumps(record))
