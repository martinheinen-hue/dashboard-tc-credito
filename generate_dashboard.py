"""
generate_dashboard.py
─────────────────────
Ejecuta las 5 queries de TC de Crédito en BigQuery y genera index.html.
En GitHub Actions usa las variables de entorno GCLOUD_* para autenticarse.
"""

from google.cloud import bigquery
from google.oauth2.credentials import Credentials
import pandas as pd
import json, os, sys
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

BILLING_PROJECT = "meli-bi-data"
OUT_FILE = os.path.join(os.path.dirname(__file__), "index.html")

PRODUCT_MAP = {
    1: "Full Brasil", 2: "Full México", 3: "Colateral Brasil",
    4: "PJ Brasil",   5: "Micro Brasil", 6: "Express México",
    7: "Micro México", 8: "Full Argentina", 9: "PJ México",
}

# ── Rango dinámico: últimos 12 meses completos ──────────────────────────────
def get_date_range():
    today = date.today()
    end   = (today.replace(day=1) - relativedelta(days=1))          # último día mes anterior
    start = (end.replace(day=1)   - relativedelta(months=11))       # 12 meses atrás
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

START_DATE, END_DATE = get_date_range()

# ── Queries ─────────────────────────────────────────────────────────────────
Q1 = f"""
WITH historial AS (
  SELECT CUS_CUST_ID, SIT_SITE_ID,
    DATE_TRUNC(DATE(MIN(CCARD_PROP_CREATION_DT)), MONTH) AS mes_primer
  FROM `meli-bi-data.WHOWNER.BT_CCARD_PROPOSAL`
  WHERE DATE(CCARD_PROP_CREATION_DT) >= '2020-01-01'
  GROUP BY 1,2
),
periodo AS (
  SELECT
    DATE_TRUNC(DATE(p.CCARD_PROP_CREATION_DT), MONTH) AS mes,
    p.SIT_SITE_ID, p.CCARD_PRODUCT_ID, h.mes_primer
  FROM `meli-bi-data.WHOWNER.BT_CCARD_PROPOSAL` p
  LEFT JOIN historial h ON p.CUS_CUST_ID=h.CUS_CUST_ID AND p.SIT_SITE_ID=h.SIT_SITE_ID
  WHERE DATE(p.CCARD_PROP_CREATION_DT) BETWEEN '{START_DATE}' AND '{END_DATE}'
)
SELECT
  FORMAT_DATE('%Y-%m', mes)        AS mes,
  SIT_SITE_ID,
  CCARD_PRODUCT_ID                 AS producto_id,
  COUNT(*)                         AS total_encendidos,
  COUNTIF(mes=mes_primer)          AS primeros_encendidos,
  COUNT(*)-COUNTIF(mes=mes_primer) AS reencendidos
FROM periodo
GROUP BY 1,2,3 ORDER BY 1,2,3
"""

Q2 = f"""
SELECT
  FORMAT_DATE('%Y-%m', DATE_TRUNC(DATE(CCARD_ACCOUNT_CREATION_DT),MONTH)) AS mes,
  SIT_SITE_ID, CCARD_PROD_ID AS producto_id, COUNT(*) AS total_emisiones
FROM `meli-bi-data.WHOWNER.BT_CCARD_ACCOUNT`
WHERE DATE(CCARD_ACCOUNT_CREATION_DT) BETWEEN '{START_DATE}' AND '{END_DATE}'
GROUP BY 1,2,3 ORDER BY 1,2,3
"""

Q3 = f"""
SELECT
  FORMAT_DATE('%Y-%m', DATE_TRUNC(DATE(CCARD_PURCH_OP_DT),MONTH)) AS mes,
  SIT_SITE_ID,
  CCARD_PURCH_OP_CARD_TYPE                  AS tipo_tarjeta,
  ROUND(SUM(CCARD_PURCH_OP_ORIG_AMT_USD),2) AS tpv_total_usd,
  COUNT(*)                                  AS cantidad_trx
FROM `meli-bi-data.WHOWNER.BT_CCARD_PURCHASE`
WHERE DATE(CCARD_PURCH_OP_DT) BETWEEN '{START_DATE}' AND '{END_DATE}'
  AND CCARD_PURCH_OP_TYPE='purchase' AND CCARD_PURCH_OP_STATUS='approved'
GROUP BY 1,2,3 ORDER BY 1,2
"""

Q4 = f"""
WITH cuentas AS (
  SELECT CCARD_ACCOUNT_ID, SIT_SITE_ID, CCARD_PROD_ID,
    DATE(CCARD_ACCOUNT_CREATION_DT) AS fecha_emision,
    FORMAT_DATE('%Y-%m', DATE_TRUNC(DATE(CCARD_ACCOUNT_CREATION_DT),MONTH)) AS mes_emision
  FROM `meli-bi-data.WHOWNER.BT_CCARD_ACCOUNT`
  WHERE DATE(CCARD_ACCOUNT_CREATION_DT) BETWEEN '{START_DATE}' AND '{END_DATE}'
),
tpv AS (
  SELECT c.CCARD_ACCOUNT_ID, c.SIT_SITE_ID, c.CCARD_PROD_ID, c.mes_emision,
    COALESCE(SUM(p.CCARD_PURCH_OP_ORIG_AMT_USD),0) AS tpv_30d
  FROM cuentas c
  LEFT JOIN `meli-bi-data.WHOWNER.BT_CCARD_PURCHASE` p
    ON c.CCARD_ACCOUNT_ID=p.CCARD_ACCOUNT_ID
    AND p.CCARD_PURCH_OP_TYPE='purchase' AND p.CCARD_PURCH_OP_STATUS='approved'
    AND DATE(p.CCARD_PURCH_OP_DT) BETWEEN c.fecha_emision
        AND DATE_ADD(c.fecha_emision, INTERVAL 30 DAY)
  GROUP BY 1,2,3,4
)
SELECT mes_emision AS mes, SIT_SITE_ID, CCARD_PROD_ID AS producto_id,
  COUNT(*) AS cuentas_emitidas, ROUND(AVG(tpv_30d),2) AS tpv_promedio_usd
FROM tpv GROUP BY 1,2,3 ORDER BY 1,2,3
"""

Q5 = f"""
WITH historial AS (
  SELECT CUS_CUST_ID, SIT_SITE_ID,
    DATE_TRUNC(DATE(MIN(CCARD_PROP_CREATION_DT)),MONTH) AS mes_primer
  FROM `meli-bi-data.WHOWNER.BT_CCARD_PROPOSAL`
  WHERE DATE(CCARD_PROP_CREATION_DT) >= '2020-01-01'
  GROUP BY 1,2
),
primeros AS (
  SELECT FORMAT_DATE('%Y-%m',mes_primer) AS mes, SIT_SITE_ID, COUNT(*) AS primeros_enc
  FROM historial
  WHERE mes_primer BETWEEN '{START_DATE}' AND '{END_DATE}'
  GROUP BY 1,2
),
emisiones AS (
  SELECT FORMAT_DATE('%Y-%m',DATE_TRUNC(DATE(CCARD_ACCOUNT_CREATION_DT),MONTH)) AS mes,
    SIT_SITE_ID, COUNT(*) AS total_emisiones
  FROM `meli-bi-data.WHOWNER.BT_CCARD_ACCOUNT`
  WHERE DATE(CCARD_ACCOUNT_CREATION_DT) BETWEEN '{START_DATE}' AND '{END_DATE}'
  GROUP BY 1,2
)
SELECT
  COALESCE(e.mes,p.mes) AS mes,
  COALESCE(e.SIT_SITE_ID,p.SIT_SITE_ID) AS SIT_SITE_ID,
  COALESCE(e.total_emisiones,0) AS total_emisiones,
  COALESCE(p.primeros_enc,0) AS primeros_encendidos,
  ROUND(SAFE_DIVIDE(COALESCE(e.total_emisiones,0),
        COALESCE(p.primeros_enc,0))*100,2) AS adopcion_pct
FROM emisiones e
FULL OUTER JOIN primeros p ON e.mes=p.mes AND e.SIT_SITE_ID=p.SIT_SITE_ID
ORDER BY 1,2
"""

def get_bq_client():
    """Crea cliente BigQuery. En CI usa las variables de entorno GCLOUD_*"""
    refresh_token = os.environ.get("GCLOUD_REFRESH_TOKEN")
    if refresh_token:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ["GCLOUD_CLIENT_ID"],
            client_secret=os.environ["GCLOUD_CLIENT_SECRET"],
        )
        return bigquery.Client(project=BILLING_PROJECT, credentials=creds)
    return bigquery.Client(project=BILLING_PROJECT)

def run(client, name, sql):
    print(f"  ▶ {name}...", end=" ", flush=True)
    df = client.query(sql).to_dataframe()
    if 'producto_id' in df.columns:
        df['producto_nombre'] = df['producto_id'].map(PRODUCT_MAP).fillna(df['producto_id'].astype(str))
    print(f"{len(df)} filas")
    return df.to_dict(orient='records')

def main():
    print(f"=== Dashboard TC Crédito — Generando ({START_DATE} → {END_DATE}) ===")
    client = get_bq_client()
    data = {}
    for name, sql in [("q1",Q1),("q2",Q2),("q3",Q3),("q4",Q4),("q5",Q5)]:
        try:
            data[name] = run(client, name, sql)
        except Exception as e:
            print(f"\n  ❌ Error en {name}: {e}")
            data[name] = []

    html = build_html(data)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n✅ Dashboard generado: {OUT_FILE}")

def build_html(data):
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    data_js = json.dumps(data, ensure_ascii=False, default=str)
    desde = START_DATE[:7]
    hasta = END_DATE[:7]

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard — Tarjeta de Crédito MercadoPago</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f0f2f5;color:#1a1a2e}}
header{{background:linear-gradient(135deg,#00b1ea,#0067b1);color:#fff;padding:18px 32px;display:flex;align-items:center;justify-content:space-between}}
header h1{{font-size:1.25rem;font-weight:700}}
header small{{font-size:.8rem;opacity:.8}}
.filters{{background:#fff;padding:14px 32px;display:flex;flex-wrap:wrap;gap:18px;align-items:flex-end;border-bottom:1px solid #e0e4ea;position:sticky;top:0;z-index:100;box-shadow:0 2px 8px rgba(0,0,0,.07)}}
.fg{{display:flex;flex-direction:column;gap:4px}}
.fg label{{font-size:.7rem;font-weight:700;color:#666;text-transform:uppercase;letter-spacing:.5px}}
.fg select,.fg input{{border:1px solid #d0d0d0;border-radius:6px;padding:6px 10px;font-size:.85rem;background:#fafafa;min-width:120px;cursor:pointer}}
.fg select:focus,.fg input:focus{{outline:2px solid #00b1ea;border-color:#00b1ea}}
.cbs{{display:flex;gap:10px;flex-wrap:wrap;margin-top:2px}}
.cbs label{{display:flex;align-items:center;gap:4px;font-size:.85rem;cursor:pointer;white-space:nowrap}}
.btn-r{{background:#f0f0f0;border:1px solid #ccc;border-radius:6px;padding:7px 14px;font-size:.83rem;cursor:pointer;align-self:flex-end}}
.btn-r:hover{{background:#e0e0e0}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:18px;padding:22px 32px;max-width:1600px;margin:0 auto}}
.card{{background:#fff;border-radius:12px;box-shadow:0 1px 6px rgba(0,0,0,.07);padding:18px 22px}}
.card.fw{{grid-column:1/-1}}
.card h2{{font-size:.92rem;font-weight:700;color:#222;margin-bottom:2px}}
.card .sub{{font-size:.75rem;color:#999;margin-bottom:14px}}
.cw{{position:relative;height:270px}}
.cw-lg{{position:relative;height:250px}}
.kpi-row{{display:flex;gap:14px;flex-wrap:wrap}}
.kpi{{flex:1;min-width:130px;background:#f7f9fc;border-radius:8px;padding:14px 16px;border-left:3px solid #00b1ea}}
.kpi .v{{font-size:1.5rem;font-weight:800;color:#0067b1}}
.kpi .l{{font-size:.72rem;color:#888;margin-top:3px;line-height:1.3}}
</style>
</head>
<body>
<header>
  <div><h1>📊 Dashboard — Tarjeta de Crédito MercadoPago</h1></div>
  <small>Datos: {desde} – {hasta} &nbsp;|&nbsp; Actualizado: {ts} UTC</small>
</header>
<div class="filters">
  <div class="fg"><label>País</label>
    <div class="cbs" id="fp">
      <label><input type="checkbox" value="MLA" checked> 🇦🇷 Argentina</label>
      <label><input type="checkbox" value="MLB" checked> 🇧🇷 Brasil</label>
      <label><input type="checkbox" value="MLM" checked> 🇲🇽 México</label>
    </div>
  </div>
  <div class="fg"><label>Desde</label><input type="month" id="fd" value="{desde}"></div>
  <div class="fg"><label>Hasta</label><input type="month" id="fh" value="{hasta}"></div>
  <div class="fg"><label>Producto</label>
    <select id="fprod">
      <option value="all">Todos los productos</option>
      <option value="Full Argentina">Full Argentina</option>
      <option value="Full Brasil">Full Brasil</option>
      <option value="Full México">Full México</option>
      <option value="Micro Brasil">Micro Brasil</option>
      <option value="Micro México">Micro México</option>
      <option value="Express México">Express México</option>
      <option value="PJ Brasil">PJ Brasil</option>
      <option value="PJ México">PJ México</option>
      <option value="Colateral Brasil">Colateral Brasil</option>
    </select>
  </div>
  <div class="fg"><label>Tipo tarjeta</label>
    <select id="ftt">
      <option value="all">Todas</option>
      <option value="contactless">Física (contactless)</option>
      <option value="virtual">Virtual</option>
    </select>
  </div>
  <button class="btn-r" onclick="reset()">↺ Resetear</button>
</div>
<div class="grid">
  <div class="card fw">
    <h2>Resumen del periodo</h2><div class="sub">Totales según filtros activos</div>
    <div class="kpi-row">
      <div class="kpi"><div class="v" id="k1">—</div><div class="l">Total Encendidos</div></div>
      <div class="kpi"><div class="v" id="k2">—</div><div class="l">Primeros Encendidos</div></div>
      <div class="kpi"><div class="v" id="k3">—</div><div class="l">Re-encendidos</div></div>
      <div class="kpi"><div class="v" id="k4">—</div><div class="l">Emisiones Totales</div></div>
      <div class="kpi"><div class="v" id="k5">—</div><div class="l">TPV Total USD</div></div>
      <div class="kpi"><div class="v" id="k6">—</div><div class="l">Adopción % promedio</div></div>
    </div>
  </div>
  <div class="card">
    <h2>Encendidos por mes</h2>
    <div class="sub">Primeros encendidos vs. Re-encendidos · BT_CCARD_PROPOSAL</div>
    <div class="cw"><canvas id="c1"></canvas></div>
  </div>
  <div class="card">
    <h2>Emisiones por mes</h2>
    <div class="sub">Cuentas creadas por país · BT_CCARD_ACCOUNT</div>
    <div class="cw"><canvas id="c2"></canvas></div>
  </div>
  <div class="card">
    <h2>TPV total en USD mes a mes</h2>
    <div class="sub">Compras aprobadas por país · BT_CCARD_PURCHASE</div>
    <div class="cw"><canvas id="c3"></canvas></div>
  </div>
  <div class="card">
    <h2>TPV promedio primer mes post emisión</h2>
    <div class="sub">Promedio USD en primeros 30 días por producto</div>
    <div class="cw"><canvas id="c4"></canvas></div>
  </div>
  <div class="card fw">
    <h2>Adopción % de Tarjeta de Crédito</h2>
    <div class="sub">Emisiones / Primeros Encendidos × 100 · por mes y país</div>
    <div class="cw-lg"><canvas id="c5"></canvas></div>
  </div>
</div>
<script>
const RAW={data_js};
const C={{MLA:{{m:'#00b1ea'}},MLB:{{m:'#f7b731'}},MLM:{{m:'#26de81'}},prod:['#0067b1','#f7b731','#26de81','#e67e22','#a29bfe','#fd9644','#fc5c65','#00b1ea','#20bf6b'],primer:'#0067b1',reenc:'#90caf9'}};
const charts={{}};
const gf=()=>{{const pais=[...document.querySelectorAll('#fp input:checked')].map(i=>i.value);return{{pais,desde:document.getElementById('fd').value,hasta:document.getElementById('fh').value,prod:document.getElementById('fprod').value,tt:document.getElementById('ftt').value}};}};
const inRange=(m,d,h)=>{{const s=String(m).slice(0,7);return s>=d&&s<=h;}};
const filterRows=(rows,f,mf='mes',pf='SIT_SITE_ID',nf=null)=>rows.filter(r=>f.pais.includes(r[pf])&&inRange(r[mf],f.desde,f.hasta)&&(!nf||f.prod==='all'||r[nf]===f.prod));
const meses=(rows,mf='mes')=>[...new Set(rows.map(r=>String(r[mf]).slice(0,7)))].sort();
const sum=(rows,k)=>rows.reduce((s,r)=>s+(Number(r[k])||0),0);
const fmt=n=>n>=1e9?'$'+(n/1e9).toFixed(1)+'B':n>=1e6?(n>=1e7?'$':'')+(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'K':Math.round(n).toLocaleString();
const fmtP=n=>n?n.toFixed(1)+'%':'—';
const kill=id=>{{if(charts[id]){{charts[id].destroy();delete charts[id];}}}};
const baseOpts=(stacked,money)=>({{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'top',labels:{{font:{{size:11}},boxWidth:12}}}}}},scales:{{x:{{stacked,grid:{{color:'#f0f4f8'}},ticks:{{font:{{size:10}}}}}},y:{{stacked,grid:{{color:'#f0f4f8'}},ticks:{{font:{{size:10}},callback:v=>money?'$'+fmt(v):fmt(v)}}}}}}}});
function kpis(f){{const q1=filterRows(RAW.q1,f,'mes','SIT_SITE_ID','producto_nombre');const q2=filterRows(RAW.q2,f,'mes','SIT_SITE_ID','producto_nombre');const q3=RAW.q3.filter(r=>f.pais.includes(r.SIT_SITE_ID)&&inRange(r.mes,f.desde,f.hasta)&&(f.tt==='all'||r.tipo_tarjeta===f.tt));const q5=filterRows(RAW.q5,f,'mes','SIT_SITE_ID');document.getElementById('k1').textContent=fmt(sum(q1,'total_encendidos'));document.getElementById('k2').textContent=fmt(sum(q1,'primeros_encendidos'));document.getElementById('k3').textContent=fmt(sum(q1,'reencendidos'));document.getElementById('k4').textContent=fmt(sum(q2,'total_emisiones'));document.getElementById('k5').textContent='$'+fmt(sum(q3,'tpv_total_usd'));const ar=q5.filter(r=>r.adopcion_pct>0);document.getElementById('k6').textContent=fmtP(ar.length?ar.reduce((s,r)=>s+r.adopcion_pct,0)/ar.length:0);}}
function c1(f){{kill('c1');const rows=filterRows(RAW.q1,f,'mes','SIT_SITE_ID','producto_nombre');const ms=meses(rows);const bm={{}};ms.forEach(m=>bm[m]={{p:0,r:0}});rows.forEach(r=>{{const m=String(r.mes).slice(0,7);if(bm[m]){{bm[m].p+=r.primeros_encendidos||0;bm[m].r+=r.reencendidos||0;}}}});charts['c1']=new Chart(document.getElementById('c1'),{{type:'bar',data:{{labels:ms,datasets:[{{label:'Primeros encendidos',data:ms.map(m=>bm[m].p),backgroundColor:C.primer,stack:'s'}},{{label:'Re-encendidos',data:ms.map(m=>bm[m].r),backgroundColor:C.reenc,stack:'s'}}]}},options:baseOpts(true,false)}});}}
function c2(f){{kill('c2');const rows=filterRows(RAW.q2,f,'mes','SIT_SITE_ID','producto_nombre');const ms=meses(rows);const ps=f.pais;const bm={{}};ms.forEach(m=>{{bm[m]={{}};ps.forEach(p=>bm[m][p]=0);}});rows.forEach(r=>{{const m=String(r.mes).slice(0,7);if(bm[m]&&bm[m][r.SIT_SITE_ID]!==undefined)bm[m][r.SIT_SITE_ID]+=r.total_emisiones||0;}});charts['c2']=new Chart(document.getElementById('c2'),{{type:'bar',data:{{labels:ms,datasets:ps.map(p=>{{return{{label:p,data:ms.map(m=>bm[m]?.[p]||0),backgroundColor:C[p]?.m||'#aaa',stack:'s'}};}})}},options:baseOpts(true,false)}});}}
function c3(f){{kill('c3');const rows=RAW.q3.filter(r=>f.pais.includes(r.SIT_SITE_ID)&&inRange(r.mes,f.desde,f.hasta)&&(f.tt==='all'||r.tipo_tarjeta===f.tt));const ms=meses(rows);const ps=f.pais;const bm={{}};ms.forEach(m=>{{bm[m]={{}};ps.forEach(p=>bm[m][p]=0);}});rows.forEach(r=>{{const m=String(r.mes).slice(0,7);if(bm[m]&&bm[m][r.SIT_SITE_ID]!==undefined)bm[m][r.SIT_SITE_ID]+=r.tpv_total_usd||0;}});charts['c3']=new Chart(document.getElementById('c3'),{{type:'bar',data:{{labels:ms,datasets:ps.map(p=>{{return{{label:p,data:ms.map(m=>Math.round(bm[m]?.[p]||0)),backgroundColor:C[p]?.m||'#aaa',stack:'s'}};}})}},options:baseOpts(true,true)}});}}
function c4(f){{kill('c4');const rows=filterRows(RAW.q4,f,'mes','SIT_SITE_ID','producto_nombre');const ms=meses(rows);const prods=[...new Set(rows.map(r=>r.producto_nombre))].sort();const bm={{}};rows.forEach(r=>{{const m=String(r.mes).slice(0,7);if(!bm[m])bm[m]={{}};bm[m][r.producto_nombre]=(bm[m][r.producto_nombre]||[]);bm[m][r.producto_nombre].push(r.tpv_promedio_usd||0);}});charts['c4']=new Chart(document.getElementById('c4'),{{type:'bar',data:{{labels:ms,datasets:prods.map((p,i)=>{{return{{label:p,data:ms.map(m=>{{const v=bm[m]?.[p];return v?+(v.reduce((s,x)=>s+x,0)/v.length).toFixed(2):null;}}),backgroundColor:C.prod[i%C.prod.length]}};}})}},options:baseOpts(false,true)}});}}
function c5(f){{kill('c5');const rows=filterRows(RAW.q5,f,'mes','SIT_SITE_ID');const ms=meses(rows);const ps=f.pais;const bm={{}};rows.forEach(r=>{{const m=String(r.mes).slice(0,7);if(!bm[m])bm[m]={{}};bm[m][r.SIT_SITE_ID]=r.adopcion_pct;}});charts['c5']=new Chart(document.getElementById('c5'),{{type:'line',data:{{labels:ms,datasets:ps.map(p=>{{return{{label:p,data:ms.map(m=>bm[m]?.[p]??null),borderColor:C[p]?.m||'#aaa',backgroundColor:(C[p]?.m||'#aaa')+'22',fill:false,tension:.35,pointRadius:4,borderWidth:2.5}};}})}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'top',labels:{{font:{{size:11}},boxWidth:12}}}},tooltip:{{callbacks:{{label:ctx=>`${{ctx.dataset.label}}: ${{ctx.parsed.y?.toFixed(1)}}%`}}}}}},scales:{{y:{{grid:{{color:'#f0f4f8'}},ticks:{{callback:v=>v+'%',font:{{size:10}}}}}},x:{{grid:{{color:'#f0f4f8'}},ticks:{{font:{{size:10}}}}}}}}}}}});}}
function renderAll(){{const f=gf();kpis(f);c1(f);c2(f);c3(f);c4(f);c5(f);}}
function reset(){{document.querySelectorAll('#fp input').forEach(i=>i.checked=true);document.getElementById('fd').value='{desde}';document.getElementById('fh').value='{hasta}';document.getElementById('fprod').value='all';document.getElementById('ftt').value='all';renderAll();}}
document.querySelectorAll('.filters input,.filters select').forEach(el=>el.addEventListener('change',renderAll));
renderAll();
</script>
</body>
</html>"""

if __name__ == "__main__":
    main()
