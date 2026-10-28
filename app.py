import os, random, sqlite3, time, math
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template
app=Flask(__name__)
DB=os.environ.get('DATABASE_PATH','/tmp/aether.sqlite3')
def connect():
 c=sqlite3.connect(DB);c.execute('CREATE TABLE IF NOT EXISTS experiments(id INTEGER PRIMARY KEY,created TEXT, hypothesis TEXT, trials INTEGER, estimate REAL, expected REAL, deviation REAL, status TEXT)');return c
@app.get('/')
def home():return render_template('index.html')
@app.get('/api/results')
def results():
 with connect() as c:
  rows=c.execute('SELECT id,created,hypothesis,trials,estimate,expected,deviation,status FROM experiments ORDER BY id DESC LIMIT 100').fetchall()
 return jsonify([dict(zip(['id','created','hypothesis','trials','estimate','expected','deviation','status'],r)) for r in rows])
@app.post('/api/run')
def run():
 # Reproducible mathematical baseline: estimate pi via uniform sampling in unit square.
 n=20000;inside=sum(random.random()**2+random.random()**2<=1 for _ in range(n));estimate=4*inside/n;deviation=abs(estimate-math.pi)
 with connect() as c:
  c.execute('INSERT INTO experiments(created,hypothesis,trials,estimate,expected,deviation,status) VALUES(?,?,?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),'Monte Carlo circle-area estimate of pi',n,estimate,math.pi,deviation,'completed'))
 return jsonify({'estimate':estimate,'expected':math.pi,'deviation':deviation,'trials':n})
@app.get('/health')
def health():return jsonify(status='ok')
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',10000)))
