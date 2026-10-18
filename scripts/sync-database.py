"""Read the supplied workbook's cached values; never rewrite the workbook.

Usage: python scripts/sync-database.py --workbook data/Database_v4_reconciled.xlsx
       --sources /path/to/reports --cbr-xml /path/to/cbr-usd.xml
"""
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from datetime import date, datetime, timedelta
import argparse, hashlib, json, math, re, shutil

ROOT = Path(__file__).resolve().parents[1]
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
TICKERS = ['LKOH','GAZP','YDEX','T','TATN','NVTK','GMKN','OZON','X5','ROSN','PLZL','SNGS','HEAD','MTSS','IRAO','CHMF','RUAL','NLMK','PHOR','RTKM','AFLT','MAGN','ENPG','MDMG','LENT','FLOT','BSPB','ALRS','CNRU','AFKS','UGLD','POSI','VKCO','RAGR']
NAMES = {'T':'Т-Технологии','X5':'X5 Group','AFKS':'АФК Система','YDEX':'Яндекс','NVTK':'НОВАТЭК','TATN':'Татнефть','GMKN':'Норникель','OZON':'Ozon','SNGS':'Сургутнефтегаз','MDMG':'Мать и дитя','BSPB':'Банк Санкт-Петербург','UGLD':'ЮГК','POSI':'Группа Позитив','VKCO':'VK','RAGR':'Русагро','ENPG':'Эн+','FLOT':'Совкомфлот','CNRU':'Циан','ALRS':'АЛРОСА'}
SECTORS = {'LKOH':['Нефть и газ'],'GAZP':['Нефть и газ'],'YDEX':['IT','E-commerce'],'T':['Банки','Финтех'],'TATN':['Нефть и газ'],'NVTK':['Нефть и газ'],'GMKN':['Цветная металлургия'],'OZON':['E-commerce','IT','Финтех'],'X5':['Продуктовый ритейл'],'ROSN':['Нефть и газ'],'PLZL':['Золотодобыча'],'SNGS':['Нефть и газ'],'HEAD':['IT','Онлайн-рекрутмент'],'MTSS':['Телекоммуникации','IT'],'IRAO':['Электроэнергетика'],'CHMF':['Черная металлургия'],'RUAL':['Цветная металлургия'],'NLMK':['Черная металлургия'],'PHOR':['Удобрения'],'RTKM':['Телекоммуникации','IT'],'AFLT':['Авиаперевозки'],'MAGN':['Черная металлургия'],'ENPG':['Цветная металлургия','Электроэнергетика'],'MDMG':['Медицина'],'LENT':['Продуктовый ритейл'],'FLOT':['Морские перевозки'],'BSPB':['Банки'],'ALRS':['Алмазодобыча'],'CNRU':['IT','Онлайн-недвижимость'],'AFKS':['Инвестиционные холдинги'],'UGLD':['Золотодобыча'],'POSI':['IT','Кибербезопасность'],'VKCO':['IT','Интернет-сервисы'],'RAGR':['Агропромышленный комплекс']}
FIELDS = {'nd':'E','rev':'H','ebitda':'I','adjusted':'J','pre16':'K','ebitdac':'L','oibda':'M','profit':'N','book':'O'}
SOURCE_COL = {'nd':'BC','rev':'BF','adjusted':'BG','pre16':'BH','ebitda':'BI','ebitdac':'BJ','oibda':'BK','profit':'BL','book':'BM'}
PERIODS = {'2025':'Фин.показатели 2025','1H2025':'1 пол. 2025','1H2026':'1 пол. 2026','TTM':'Фин.показатели TTM'}

def numeric(x):
    return x if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) else None

def workbook_cells(path):
    with ZipFile(path) as z:
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            shared=[''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml'))]
        rels={n.attrib['Id']:n.attrib['Target'].lstrip('/') for n in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        sheets={}
        for sheet in ET.fromstring(z.read('xl/workbook.xml')).find('s:sheets',NS):
            target=rels[sheet.attrib['{'+R+'}id']]
            if not target.startswith('xl/'):target='xl/'+target
            cells={}
            for c in ET.fromstring(z.read(target)).findall('.//s:sheetData/s:row/s:c',NS):
                v=c.find('s:v',NS);value=v.text if v is not None else None;t=c.attrib.get('t')
                if t=='s' and value is not None:value=shared[int(value)]
                elif t=='inlineStr':value=''.join(c.find('s:is',NS).itertext())
                elif value is not None and t not in ('str','e'):
                    try:value=float(value)
                    except ValueError:pass
                cells[c.attrib['r']]=value
            sheets[sheet.attrib['name']]=cells
        return sheets

def fx_rates(xml_path):
    rows={datetime.strptime(n.attrib['Date'],'%d.%m.%Y').date():float(n.findtext('Value').replace(',','.'))/float(n.findtext('Nominal')) for n in ET.fromstring(Path(xml_path).read_bytes())}
    result={}
    for year in [2023,2024]:
        d=date(year,1,1);last=max((x for x in rows if x<=d),default=None)
        if last is None:raise ValueError('CBR history must include the rate effective on January 1')
        rate=rows[last];values=[]
        while d.year==year:
            rate=rows.get(d,rate);values.append(rate);d+=timedelta(days=1)
        result[str(year)]={'average':sum(values)/len(values),'closing':values[-1]}
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workbook',type=Path,required=True);p.add_argument('--sources',type=Path,action='append',default=[]);p.add_argument('--cbr-xml',type=Path);args=p.parse_args()
    wb=workbook_cells(args.workbook);public=ROOT/'public';base=json.loads((public/'data.json').read_text());old={c['id']:c for c in base['companies']}
    rates_path=ROOT/'data/currency-rates.json'
    rates=fx_rates(args.cbr_xml) if args.cbr_xml else json.loads(rates_path.read_text())['rates']
    rates_path.write_text(json.dumps({'source':'https://www.cbr.ru/scripts/XML_dynamic.asp','method':'Average of daily effective official rates over calendar days; closing rate for balance-sheet values.','rates':rates},indent=2)+'\n')
    files=[]
    for folder in args.sources:
        files.extend(f for f in folder.rglob('*') if f.is_file() and f.suffix.lower() in {'.pdf','.png','.jpg','.jpeg','.xlsx'})
    by_name={}
    for f in files:by_name.setdefault(f.name.casefold(),[]).append(f)
    used={};rendered={};unresolved=set();sources_count=0

    def attach(c,path):
        key=(c['id'],str(path.resolve()))
        if key in used:return used[key]
        digest=hashlib.sha256(path.read_bytes()).hexdigest()[:20];url=f"assets/{c['id']}/{digest}{path.suffix.lower()}";out=public/url
        out.parent.mkdir(parents=True,exist_ok=True)
        if not out.exists():shutil.copy2(path,out)
        kind='image' if path.suffix.lower() in {'.png','.jpg','.jpeg'} else 'document'
        category='ir' if re.search(r'презент|presentation|release|релиз|IR[_. -]',path.name,re.I) else 'report'
        a={'name':path.name,'url':url,'size':path.stat().st_size,'kind':kind,'category':category}
        if not any(x['url']==url for x in c['assets']):c['assets'].append(a)
        used[key]=a;return a

    def screenshot(c,path,page):
        key=(str(path),page)
        if key in rendered:return rendered[key]
        try:
            import fitz
            doc=fitz.open(path)
            if page<1 or page>len(doc):return None
            digest=hashlib.sha256((str(path)+':'+str(page)).encode()).hexdigest()[:20]
            target=public/f"assets/{c['id']}/source-{digest}.png";target.parent.mkdir(parents=True,exist_ok=True)
            if not target.exists():doc[page-1].get_pixmap(matrix=fitz.Matrix(1.25,1.25),alpha=False).save(target)
            doc.close()
            a={'name':path.stem+f' · стр. {page}.png','url':str(target.relative_to(public)),'size':target.stat().st_size,'kind':'image','page':page,'category':'evidence'}
            rendered[key]=a
            if not any(x['url']==a['url'] for x in c['assets']):c['assets'].append(a)
            return a
        except Exception:return None

    def evidence(c,text,period,metric):
        nonlocal sources_count
        text=str(text or '');docs=[];images=[]
        # Match complete known filenames, including spaces and hyphens. Page references
        # commonly follow a semicolon, so they must not be truncated at that delimiter.
        lower=text.casefold()
        matches=sorted([(lower.index(name),name,paths[0]) for name,paths in by_name.items() if name.endswith('.pdf') and name in lower])
        for position,name,path in matches:
            doc=attach(c,path);docs.append(doc)
            following=text[position+len(name):position+len(name)+300]
            page_match=re.search(r'(?:стр\.?|с\.|page)\s*([\d,\s–—-]+)',following,re.I)
            pages=[]
            if page_match:
                for start,end in re.findall(r'(\d+)(?:\s*[-–—]\s*(\d+))?',page_match.group(1)):
                    pages.extend(range(int(start),min(int(end or start),int(start)+2)+1))
            for page in dict.fromkeys(pages[:3]):
                image=screenshot(c,path,page)
                if image:images.append(image)
        if '.pdf' in lower and not docs:unresolved.add(text[:160])
        sources_count+=bool(docs)
        return {'text':text,'page':', '.join(str(x['page']) for x in images),'document':docs[0] if docs else None,'documents':docs,'images':images,'note':'Сравнительная колонка в отчете за 2025 год.' if period=='2024' and '2025' in text else ''}

    companies=[];hist=wb['Финансы 3 года'];main_sheet=wb['Main']
    main_map={'price':'U','marketCap':'X','enterpriseValue':'AF','ev':'F','evadj':'G','evpre16':'H','evc':'I','evoibda':'J','evrev':'K','pe':'L','pb':'M','ps':'N','ndratio':'O','ndadj':'P','ndoibda':'S'}
    for idx,ticker in enumerate(TICKERS):
        mr=idx+11;fr=idx+7;prior=old.get(ticker,{})
        c={'id':ticker,'name':NAMES.get(ticker,prior.get('name') or main_sheet.get('C'+str(mr))),'currency':'RUB','sectors':SECTORS[ticker],'sector':' · '.join(SECTORS[ticker]),'assets':[],'quotes':prior.get('quotes',[]),'quoteDate':prior.get('quoteDate'),'quoteSource':prior.get('quoteSource','Сохраненная история MOEX'),'history':{},'sourcesByYear':{},'priceBasis':'Средняя цена за последние 30 дней из базы','index':idx}
        c.update({k:(numeric(main_sheet.get(col+str(mr)))/(1000 if k in ['marketCap','enterpriseValue'] else 1) if numeric(main_sheet.get(col+str(mr))) is not None else None) for k,col in main_map.items()})
        for yr,sn in PERIODS.items():
            s=wb[sn];h={k:numeric(s.get(col+str(fr))) for k,col in FIELDS.items()}
            h={k:v/1000 if v is not None else None for k,v in h.items()};h['currency']='RUB';h['note']=s.get('BR'+str(fr)) or ''
            c['history'][yr]=h;c['sourcesByYear'][yr]={}
            if yr!='TTM':
                for k in FIELDS:
                    c['sourcesByYear'][yr][k]=evidence(c,s.get(SOURCE_COL[k]+str(fr)),yr,k)
        for row in range(5,110):
            if hist.get('B'+str(row))!=ticker:continue
            year=str(int(hist.get('C'+str(row),0)))
            if year=='2025':continue
            currency=hist.get('D'+str(row));h={};native={}
            for key,col in {'rev':'E','profit':'F','ebitda':'G','adjusted':'H','pre16':'I','ebitdac':'J','oibda':'K','nd':'S'}.items():
                n=numeric(hist.get(col+str(row)));native[key]=n
                rate=rates[year]['closing' if key=='nd' else 'average'] if currency=='USD' else 1
                h[key]=n*rate/1000 if n is not None else None
            h.update(currency='RUB',nativeCurrency=currency,nativeValues=native,fx=rates[year] if currency=='USD' else None)
            c['history'][year]=h;c['sourcesByYear'][year]={}
            source=hist.get('T'+str(row));page=hist.get('U'+str(row))
            for k in h:
                if k in FIELDS:c['sourcesByYear'][year][k]=evidence(c,f'{source}; PDF стр. {page}' if source else '',year,k)
        c.update(c['history']['TTM']);c['currency']='RUB'
        c['note']=c['history']['TTM'].get('note','')
        c['sources']=c['sourcesByYear']['2025']
        c['variants']=[{'key':k,'label':label} for k,label in [('adjusted','Скорр. EBITDA'),('pre16','EBITDA IAS 17'),('ebitdac','EBITDAC'),('oibda','OIBDA')] if any(numeric(h.get(k)) is not None for h in c['history'].values())]
        c['ebitdaNote']='Версии EBITDA показаны отдельно по определениям компании.'
        # Keep original documents available, without old screenshots masquerading as new evidence.
        for a in prior.get('assets',[]):
            if a['kind']=='document' and (public/a['url']).is_file() and not any(x['name']==a['name'] for x in c['assets']):c['assets'].append(a)
        companies.append(c)
    logo_meta=json.loads((ROOT/'data/logo-sources.json').read_text()) if (ROOT/'data/logo-sources.json').exists() else {}
    ir_meta=json.loads((ROOT/'data/ir-materials.json').read_text()) if (ROOT/'data/ir-materials.json').exists() else {}
    for c in companies:
        if c['id'] in logo_meta:c['logo']='logos/'+Path(logo_meta[c['id']]['file']).name
        c['irMaterials']=[ir_meta[c['id']]] if c['id'] in ir_meta else []
    payload={'companies':companies,'period':'TTM','periodLabel':'TTM на 30.06.2026','periods':['2023','2024','2025','1H2025','1H2026','TTM'],'quoteDate':base['quoteDate'],'source':args.workbook.name,'sourceHash':hashlib.sha256(args.workbook.read_bytes()).hexdigest(),'databaseUpdatedAt':'2026-10-13','currency':'RUB','units':'млрд руб.','currencyRates':rates,'currencyRateSource':'https://www.cbr.ru/scripts/XML_dynamic.asp'}
    text=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    (public/'data.json').write_text(text);(public/'data.js').write_text('window.FMD_DATA='+text+';\n')
    report={'companies':len(companies),'sourceHash':payload['sourceHash'],'attachedDocuments':sum(a['kind']=='document' for c in companies for a in c['assets']),'screenshots':len(rendered),'unresolvedFiles':sorted(unresolved)}
    (ROOT/'data/sync-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='unresolvedFiles'},ensure_ascii=False))

if __name__=='__main__':main()
