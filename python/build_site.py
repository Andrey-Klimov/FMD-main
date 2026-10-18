"""Build FMD from local MSFO analyst data, without loading .env or application secrets."""
from pathlib import Path, PureWindowsPath
import argparse, hashlib, json, math, shutil
import openpyxl

def number(v):
    return float(v) if isinstance(v, (int,float)) and not isinstance(v,bool) and math.isfinite(v) else None

def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    wbpath=root/'baza_v2/01_base/agr_base.xlsx'
    cachepath=root/'data/landing_data.json'
    if not wbpath.is_file() or not cachepath.is_file():
        raise SystemExit('Нужны baza_v2/01_base/agr_base.xlsx и data/landing_data.json в папке проекта.')
    if output == root or output in root.parents:
        raise SystemExit('Папка результата не может совпадать с папкой проекта или содержать её.')
    web=Path(__file__).resolve().parent/'fmd_web'
    output.mkdir(parents=True,exist_ok=True)
    # Remove only previously generated public assets, never source data.
    if (output/'assets').exists(): shutil.rmtree(output/'assets')
    for p in web.iterdir():
        if p.is_file(): shutil.copy2(p,output/p.name)
    cached={c['ticker']:c for c in json.loads(cachepath.read_text(encoding='utf-8'))}
    wb=openpyxl.load_workbook(wbpath,read_only=True,data_only=True)
    history={}
    keys={'rev':4,'profit':5,'ebitda':6,'adjusted':7,'pre16':8,'ebitdac':9,'oibda':10,'nd':18}
    for r in list(wb['Финансы 3 года'].values)[4:]:
        if not r[1] or not isinstance(r[2],(int,float)): continue
        history.setdefault(r[1],{})[str(int(r[2]))]={**{k:(number(r[i])/1000 if number(r[i]) is not None else None) for k,i in keys.items()},'currency':r[3],'file':r[19],'page':str(r[20] or '')}
    base=root/'baza_v2'; reports=base/'03_Отчетность_и_скриншоты'
    companies=[]
    for row in list(wb['Сводная база'].values)[5:]:
        ticker=row[2]
        if not ticker or ticker not in cached: continue
        raw=cached[ticker]; currency=row[5]; h=history.get(ticker,{})
        market=raw.get('market') or {}; series=market.get('series') or []
        series=sorted([s for s in series if number(s.get('price')) is not None],key=lambda s:s['date'])
        latest=series[-1] if series else {}; now=h.get('2025',{})
        def billions(i):
            n=number(row[i]); return n/1000 if n is not None else None
        c={'id':ticker,'name':row[1],'sector':row[3], 'desc':row[3], 'currency':currency,'history':h,
           'rev':billions(6),'profit':billions(7),'nd':billions(23),'ebitda':now.get('ebitda'),
           'price':latest.get('price'),'quoteDate':latest.get('date'),'quotes':series,
           'quoteSource':market.get('source'),'updatedAt':market.get('updated_at'),
           'color':'#697789','index':len(companies),'assets':[],'sources':{},'pb':None}
        # IFRS history gives GMKN EBITDA in USD; cached issuer EBITDA is RUB and cannot be mixed.
        if c['ebitda'] is None:
            c['ebitda']=next((billions(i) for i in (8,9,10) if number(row[i]) is not None),None)
        c['ebitdaNote']='EBITDA из листа «Финансы 3 года»; варианты не подменяют друг друга.'
        if ticker=='GMKN': c['ebitdaNote']='EBITDA по МСФО в USD. Рублёвый показатель из отчёта эмитента исключён из расчётов в USD.'
        variants=[]
        for k,label in [('adjusted','Скорректированная EBITDA'),('pre16','EBITDA до IFRS 16'),('ebitdac','EBITDAC'),('oibda','OIBDA')]:
            if now.get(k) is not None: variants.append({'key':k,'label':label,'value':now[k]})
        c['variants']=variants
        # Recalculate with the reporting-currency market cap stored in the source cache.
        cap=number(latest.get('market_cap_reporting_mln'))
        if currency=='RUB' and cap is None: cap=number(latest.get('market_cap_mln'))
        cap=cap/1000 if cap is not None else None
        enterprise=cap+c['nd'] if cap is not None and c['nd'] is not None else None
        bank=ticker in ('T','BSPB')
        if bank: enterprise=None
        c['pe']=cap/c['profit'] if cap is not None and c['profit'] is not None and c['profit']>0 else None
        c['ev']=enterprise/c['ebitda'] if enterprise is not None and c['ebitda'] is not None and c['ebitda']>0 else None
        c['evrev']=enterprise/c['rev'] if enterprise is not None and c['rev'] is not None and c['rev']>0 else None
        c['evc']=enterprise/now['ebitdac'] if enterprise is not None and now.get('ebitdac',0) and now['ebitdac']>0 else None
        c['ndratio']=c['nd']/c['ebitda'] if not bank and c['nd'] is not None and c['ebitda'] is not None and c['ebitda']>0 else None
        c['marketCap']=cap; c['enterpriseValue']=enterprise; c['fxRate']=latest.get('fx_rate')
        def growth(key,year,n):
            start=h.get(str(year),{}).get(key); end=c.get(key)
            # No imputed values or growth when definitions changed.
            if end is None or start is None or start<=0 or (n>1 and end<=0): return None
            if key=='ebitda' and now.get(key)!=end:return None
            return ((end/start)**(1/n)-1)*100
        c.update(gr=growth('rev',2024,1),ge=growth('ebitda',2024,1),cr=growth('rev',2023,2),ce=growth('ebitda',2023,2))
        folders=[]
        if raw.get('folder'): folders.append(reports/PureWindowsPath(raw['folder']).name)
        for s in raw.get('sources',[]):
            rel=str(s.get('path') or '').replace('\\','/')
            if rel: folders.append(base/rel)
        # Include only known financial reports/evidence, not arbitrary application files.
        folders=[p.resolve() for p in folders if p.is_dir() and reports.resolve() in p.resolve().parents]
        files={p.resolve() for folder in folders for p in folder.rglob('*') if p.is_file() and p.suffix.lower() in ('.pdf','.png','.jpg','.jpeg','.docx','.rtf')}
        statement=base/'04_МСФО_Excel'/f'{ticker}_МСФО_2025.xlsx'
        if statement.is_file():files.add(statement.resolve())
        mapping={}
        for p in sorted(files):
            name=hashlib.sha256(str(p.relative_to(base)).encode()).hexdigest()[:16]+p.suffix.lower()
            url=f'assets/{ticker}/{name}'; target=output/url;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
            entry={'name':p.name,'url':url,'size':p.stat().st_size,'kind':'image' if p.suffix.lower() in ('.png','.jpg','.jpeg') else 'document'}
            c['assets'].append(entry);mapping[p.name]=entry
        for key,original in [('rev','revenue'),('profit','net_profit'),('nd','net_debt'),('ebitda','ebitda')]:
            m=raw.get('metrics',{}).get(original) or {}
            doc=mapping.get(m.get('source_file')); imgs=[mapping[e['filename']] for e in m.get('evidence',[]) if e['filename'] in mapping]
            source=m.get('source') or 'Источник не указан'; page=str(m.get('source_page') or '')
            cached_value=number(m.get('value_raw')); actual=c.get(key)
            if key=='ebitda' and (cached_value is None or actual is None or abs(cached_value/1000-actual)>1e-7):
                doc=mapping.get(now.get('file')); page=now.get('page') or '';source='Лист «Финансы 3 года» · '+str(now.get('file') or 'agr_base.xlsx')
                imgs=[x for x in c['assets'] if x['kind']=='image' and 'МСФО' in x['name'] and 'EBITDA' in x['name']]
            c['sources'][key]={'text':source,'page':page,'document':doc,'images':imgs,'note':c['ebitdaNote'] if key=='ebitda' else ''}
        companies.append(c)
    wb.close()
    payload={'companies':companies,'period':2025,'quoteDate':max((c['quoteDate'] or '' for c in companies),default=''),'source':'agr_base.xlsx + landing_data.json','sourceHash':hashlib.sha256(wbpath.read_bytes()).hexdigest()}
    encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    (output/'data.js').write_text('window.FMD_DATA='+encoded+';\n',encoding='utf-8')
    (output/'data.json').write_text(encoded,encoding='utf-8')
    print(f'FMD: {len(companies)} компаний, {sum(len(c["assets"]) for c in companies)} файлов источников. Результат: {output}')
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();build(args.root,args.output or args.root/'fmd_public')
