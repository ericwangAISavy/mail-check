"""Small, fixed-host Google Sheets transport. Writes always use literal values."""
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
import httpx

class GoogleError(ValueError):
    pass

def spreadsheet_id(value):
    value=value.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]+',value): return value
    url=urlsplit(value)
    match=re.fullmatch(r'/spreadsheets/d/([A-Za-z0-9_-]+)(?:/.*)?',url.path)
    if url.scheme!='https' or url.netloc!='docs.google.com' or not match:
        raise ValueError('Enter a Google Sheets URL or spreadsheet ID.')
    return match[1]

class SheetsClient:
    def __init__(self,token_provider,*,client=None):
        self.token_provider=token_provider
        self.client=client or httpx.Client(timeout=30)
    def request(self,method,path,**kwargs):
        try:
            for attempt in range(3 if method=='GET' else 1):
                response=self.client.request(method,'https://sheets.googleapis.com/v4/spreadsheets/'+path,headers={'Authorization':'Bearer '+self.token_provider()},**kwargs)
                if response.status_code not in (429,503) or attempt==2: break
                try: delay=min(float(response.headers.get('Retry-After',2**attempt)),5)
                except ValueError: delay=2**attempt
                time.sleep(max(delay,0))
        except httpx.HTTPError as exc:
            raise GoogleError('Google could not be reached. Reload before retrying a save.') from exc
        if response.status_code in (401,403): raise GoogleError('Reconnect Google and confirm edit access to this spreadsheet.')
        if response.status_code==404: raise GoogleError('Spreadsheet or tab was not found.')
        if response.status_code==429: raise GoogleError('Google is busy. Wait a moment before trying again.')
        if response.is_error: raise GoogleError('Google could not complete this request. Reload before retrying.')
        return response.json()
    def metadata(self,book):
        return self.request('GET',spreadsheet_id(book),params={'fields':'spreadsheetId,properties.title,sheets.properties'})
    def snapshot(self,book,tab):
        metadata=self.metadata(book)
        mapped=next((s for s in metadata.get('sheets',[]) if s['properties']['sheetId']==tab),None)
        if mapped is None: raise GoogleError('The mapped tab no longer exists.')
        title=mapped['properties']['title'].replace("'","''")
        properties=mapped['properties']
        dimensions=properties.get('gridProperties',{})
        row_count=dimensions.get('rowCount',1000)
        if row_count>100000: raise GoogleError('This tab exceeds 100,000 rows. Split it into smaller profile tabs before connecting.')
        end_column=min(dimensions.get('columnCount',101),101)
        from .sourcing import column_name
        blocks=[]
        for first in range(0,max(row_count,1),1000):
            last=min(first+1000,row_count)
            data=self.request('GET',spreadsheet_id(book),params={'includeGridData':'true','ranges':f"'{title}'!A{first+1}:{column_name(end_column-1)}{last}",'fields':'sheets(properties,data(startRow,startColumn,rowData(values(userEnteredValue,formattedValue,hyperlink))))'})
            remote=next((item for item in data.get('sheets',[]) if item['properties']['sheetId']==tab),None)
            if remote is None: raise GoogleError('The mapped tab no longer exists.')
            blocks.extend(remote.get('data',[]))
        sheet={'properties':properties,'data':blocks}
        rows=[]
        for block in sheet.get('data',[]):
            start=block.get('startRow',0)
            while len(rows)<start: rows.append([])
            for row in block.get('rowData',[]):
                cells=[]
                for cell in row.get('values',[]):
                    entered=cell.get('userEnteredValue',{})
                    value=next(iter(entered.values()),'')
                    cells.append({'value':value,'display':cell.get('formattedValue',str(value)), 'formula':'formulaValue' in entered,'link':cell.get('hyperlink','')})
                rows.append(cells)
        revision=hashlib.sha256(json.dumps(sheet,sort_keys=True).encode()).hexdigest()
        return {'rows':rows,'revision':revision,'title':sheet['properties']['title'],'properties':sheet['properties']}
    def write(self,book,patches):
        return self.request('POST',spreadsheet_id(book)+'/values:batchUpdate',json={'valueInputOption':'RAW','data':patches})

    def verify_edit(self,book):
        self.request('POST',spreadsheet_id(book)+':batchUpdate',json={'requests':[]})
    def append(self,book,title,rows):
        from urllib.parse import quote
        return self.request('POST',spreadsheet_id(book)+'/values/'+quote("'"+title.replace("'","''")+"'!A1",safe='')+':append',params={'valueInputOption':'RAW','insertDataOption':'INSERT_ROWS'},json={'values':rows})
