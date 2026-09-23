import os,json,time,secrets,base64,webbrowser,threading,urllib.parse,subprocess,platform
from pathlib import Path
import requests
from flask import Flask,request,jsonify
import tkinter as tk
from tkinter import ttk,messagebox,simpledialog

BASE=Path(__file__).resolve().parent
MAP=BASE/'mappings.json'; TOKEN=BASE/'spotify_token.json'; ENV=BASE/'.env'
HOST='0.0.0.0'; PORT=5000; CALLBACK='http://127.0.0.1:5000/callback'
AUTH='https://accounts.spotify.com/authorize'; TOKEN_URL='https://accounts.spotify.com/api/token'; API='https://api.spotify.com/v1'
SCOPE='user-read-playback-state user-modify-playback-state user-read-currently-playing'

def load_env():
    if ENV.exists():
        for x in ENV.read_text(encoding='utf8').splitlines():
            if '=' in x and not x.strip().startswith('#'):
                k,v=x.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
load_env()
CID=os.getenv('SPOTIFY_CLIENT_ID',''); SECRET=os.getenv('SPOTIFY_CLIENT_SECRET',''); REDIRECT=os.getenv('SPOTIFY_REDIRECT_URI',CALLBACK)
DEFAULT={
'DA 16 D7 30':{'name':'0001','spotify':'https://open.spotify.com/track/0oUBuOO4g9P4lREqfqR5nq'},
'0A 82 88 30':{'name':'0002','spotify':'https://open.spotify.com/track/6Frhkb7giXWjeJAX2dJT88'},
'FA CD E1 30':{'name':'0003','spotify':'https://open.spotify.com/track/5kqIPrATaCc2LqxVWzQGbk'},
'8A BE 7D 30':{'name':'0004','spotify':'https://open.spotify.com/track/3hRV0jL3vUpRrcy398teAU'},
'9A ED EA 30':{'name':'0005','spotify':'https://open.spotify.com/track/2QjOHCTQ1Jl3zawyYOpxh6'},
'0A 4A E6 30':{'name':'0006','spotify':'https://open.spotify.com/track/3qhlB30KknSejmIvZZLjOD'},
'0A 87 EF 30':{'name':'0007','spotify':'https://open.spotify.com/track/5SftJq4uVpajyYC1Gs0RFF'},
'EA 60 8B 30':{'name':'0008','spotify':'https://open.spotify.com/track/0rlLBWFFTQiOWi963SH9bb'},
'EA C6 E1 30':{'name':'0009','spotify':'https://open.spotify.com/track/5ivRSlOhVIXN2QMzqgsX0s'},
'6A 1F 73 30':{'name':'0010','spotify':'https://open.spotify.com/track/4iFPsNzNV7V9KJgcOX7TEO'},
'2A 1E 09 31':{'name':'0011','spotify':'https://open.spotify.com/track/0s76ExpXyMGVBlKLUr683e'},
'B3 66 AF 5B':{'name':'0012 / di','spotify':'https://open.spotify.com/track/7eQl3Yqv35ioqUfveKHitE'},
'B7 93 27 1F':{'name':'0013 / me','spotify':'https://open.spotify.com/track/3USxtqRwSYz57Ewm6wWRMp'},
'5F 4D 90 2F':{'name':'0014 / ujwal','spotify':''},'9F 8A 2E 2F':{'name':'0015 / soofiya','spotify':''},
'A4 8E 28 1F':{'name':'0016 / adi','spotify':'https://open.spotify.com/track/4k6Uh1HXdhtusDW5y8Gbvy'},
'CD DA 2D AB':{'name':'0017 / lucky','spotify':''},'0F 74 B3 2E':{'name':'0018 / gayan','spotify':''},
'62 BE 27 1F':{'name':'0019 / ayush','spotify':''},'17 DC 30 5F':{'name':'0020 / tanman','spotify':'https://open.spotify.com/track/3mTpegrOwRn0oJjv4TSbEE'},
'7D B1 7A 85':{'name':'0021 / taw','spotify':''},'7F 5C 17 2E':{'name':'0022 / shiv','spotify':'https://open.spotify.com/track/1lRmQ9D6oNYiuCXdGlKCs0'}}
if MAP.exists():
    try: mappings=json.loads(MAP.read_text(encoding='utf8'))
    except: mappings=DEFAULT
else:
    mappings=DEFAULT; MAP.write_text(json.dumps(mappings,indent=2),encoding='utf8')

access=None; refresh=None; expires=0; state=None; control=True
CACHED_DEVICE_ID=None
CACHED_DEVICE_NAME=None
LAST_TRACK_ID=None
if TOKEN.exists():
    try:
        t=json.loads(TOKEN.read_text()); refresh=t.get('refresh'); expires=float(t.get('expires',0))
    except: pass

def save_token():
    if refresh: TOKEN.write_text(json.dumps({'refresh':refresh,'expires':expires},indent=2),encoding='utf8')
def refresh_access():
    global access,refresh,expires
    if not refresh or not CID or not SECRET:return False
    r=requests.post(TOKEN_URL,data={'grant_type':'refresh_token','refresh_token':refresh},auth=(CID,SECRET),timeout=15)
    if r.status_code!=200:return False
    d=r.json(); access=d['access_token']; refresh=d.get('refresh_token',refresh); expires=time.time()+d.get('expires_in',3600)-60; save_token(); return True
def api(method,path,**kw):
    global access
    if not access or time.time()>=expires:
        if not refresh_access(): raise RuntimeError('Spotify is not authorized.')
    h=kw.pop('headers',{}); h['Authorization']='Bearer '+access
    r=requests.request(method,API+path,headers=h,timeout=15,**kw)
    if r.status_code==401 and refresh_access():
        h['Authorization']='Bearer '+access; r=requests.request(method,API+path,headers=h,timeout=15,**kw)
    return r

def authorize():
    global state
    if not CID or not SECRET: raise RuntimeError('Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env')
    state=secrets.token_urlsafe(24)
    q=urllib.parse.urlencode({'client_id':CID,'response_type':'code','redirect_uri':REDIRECT,'scope':SCOPE,'state':state})
    webbrowser.open(AUTH+'?'+q)
def exchange(code):
    global access,refresh,expires
    r=requests.post(TOKEN_URL,data={'grant_type':'authorization_code','code':code,'redirect_uri':REDIRECT},auth=(CID,SECRET),timeout=15)
    if r.status_code!=200: raise RuntimeError(r.text)
    d=r.json(); access=d['access_token']; refresh=d.get('refresh_token'); expires=time.time()+d.get('expires_in',3600)-60; save_token()
def devices():
    r=api('GET','/me/player/devices')
    if r.status_code!=200: raise RuntimeError(r.text)
    return r.json().get('devices',[])
def open_spotify():
    try:
        if platform.system()=='Windows': os.startfile('spotifydef laptop_device(ds):
    c=[d for d in ds if d.get('type')=='Computer' and not d.get('is_restricted')]
    return next((d for d in c if d.get('is_active')),None) or (c[0] if c else next(
        (d for d in ds if d.get('is_active') and not d.get('is_restricted')),None))

def track_id_from_url(url):
    url=(url or '').strip()
    if '/track/' in url:
        return url.split('/track/',1)[1].split('?',1)[0].split('/',1)[0]
    if url.startswith('spotify:track:'):
        return url.rsplit(':',1)[1]
    raise RuntimeError('Use a Spotify track URL.')

def current_track_id():
    try:
        r=api('GET','/me/player')
        if r.status_code in (204,):
            return None
        if r.status_code != 200:
            return None
        item=r.json().get('item') or {}
        return item.get('id')
    except Exception:
        return None

def get_cached_or_laptop_device(force_refresh=False):
    global CACHED_DEVICE_ID, CACHED_DEVICE_NAME
    if not force_refresh and CACHED_DEVICE_ID:
        return {'id': CACHED_DEVICE_ID, 'name': CACHED_DEVICE_NAME or 'Laptop', 'cached': True}
    ds=devices()
    dev=laptop_device(ds)
    if not dev:
        return None
    CACHED_DEVICE_ID=dev.get('id')
    CACHED_DEVICE_NAME=dev.get('name','Laptop')
    return dev

def play(url):
    global CACHED_DEVICE_ID, CACHED_DEVICE_NAME, LAST_TRACK_ID
    if not url:
        raise RuntimeError('No Spotify URL assigned to this card.')
    tid=track_id_from_url(url)

    # Same track already playing anywhere: do nothing.
    playing_id=current_track_id()
    if playing_id == tid:
        LAST_TRACK_ID=tid
        return 'NO_CHANGE:' + (CACHED_DEVICE_NAME or 'current Spotify device')

    open_spotify()

    # Fast path: use the cached laptop device instead of discovering it on every scan.
    dev=get_cached_or_laptop_device(force_refresh=False)

    # If the laptop Spotify client was not yet registered, wait briefly and refresh.
    if not dev:
        for _ in range(8):
            time.sleep(.5)
            dev=get_cached_or_laptop_device(force_refresh=True)
            if dev:
                break

    if not dev:
        raise RuntimeError('Spotify desktop device not found. Open Spotify desktop and sign in.')

    def send_to_device(device_id):
        r=api('PUT','/me/player',json={'device_ids':[device_id],'play':True})
        if r.status_code not in (200,204):
            return r
        return api('PUT','/me/player/play',
                   params={'device_id':device_id},
                   json={'uris':['spotify:track:'+tid]})

    did=dev['id']
    r=send_to_device(did)

    # Spotify device IDs may change. Refresh only when the cached ID fails.
    if r.status_code in (400,404):
        dev=get_cached_or_laptop_device(force_refresh=True)
        if not dev:
            raise RuntimeError('Spotify desktop device not found. Open Spotify desktop and sign in.')
        did=dev['id']
        r=send_to_device(did)

    if r.status_code not in (200,204):
        raise RuntimeError(f'Playback failed: {r.status_code} {r.text}')

    CACHED_DEVICE_ID=did
    CACHED_DEVICE_NAME=dev.get('name','Laptop')
    LAST_TRACK_ID=tid
    return CACHED_DEVICE_NAME
ayback failed: {r.status_code} {r.text}')
    return dev['name']

app=Flask(__name__)
@app.get('/callback')
def callback():
    if request.args.get('state')!=state: return '<h2>Invalid authorization state.</h2>',400
    try: exchange(request.args['code']); log('Spotify connected.'); return '<h2>Spotify connected.</h2><p>You can close this tab.</p>'
    except Exception as e: log('Spotify authorization error: '+str(e)); return '<h2>Authorization failed</h2><pre>'+str(e)+'</pre>',400
@app.post('/rfid')
def rfid():
    if not control:return jsonify(ok=False,error='RFID control OFF'),403
    uid=' '.join(str((request.get_json(silent=True) or {}).get('uid','')).upper().split())
    item=mappings.get(uid)
    if not item:return jsonify(ok=False,error='Unknown RFID',uid=uid),404
    try:
        dev=play(item.get('spotify','')); log(f"RFID {uid} → {item.get('name',uid)} → {dev}"); return jsonify(ok=True,device=dev)
    except Exception as e: log('Playback error: '+str(e)); return jsonify(ok=False,error=str(e)),500

def server(): app.run(host=HOST,port=PORT,debug=False,use_reloader=False)

root=None; tree=None; logbox=None; toggle=None

def log(s):
    if root and logbox:
        root.after(0,lambda:(logbox.insert('end',time.strftime('%H:%M:%S')+'  '+s+'\n'),logbox.see('end')))
def save(): MAP.write_text(json.dumps(mappings,indent=2,ensure_ascii=False),encoding='utf8')
def selected():
    x=tree.selection()
    return tree.item(x[0],'values')[0] if x else None
def refresh_tree():
    for x in tree.get_children():tree.delete(x)
    for uid,v in sorted(mappings.items()):tree.insert('', 'end', values=(uid,v.get('name',''),v.get('spotify','') or 'UNASSIGNED'))
def add_card():
    uid=simpledialog.askstring('Add RFID','UID:',parent=root)
    if not uid:return
    uid=' '.join(uid.upper().split())
    if uid in mappings:return messagebox.showerror('Exists','That UID already exists.',parent=root)
    name=simpledialog.askstring('Card name','Name/number:',parent=root) or uid
    url=simpledialog.askstring('Spotify URL','Spotify track URL (optional):',parent=root) or ''
    mappings[uid]={'name':name,'spotify':url.strip()};save();refresh_tree();log('Added '+uid)
def edit_card():
    uid=selected()
    if not uid:return
    v=mappings[uid]; name=simpledialog.askstring('Edit','Name/number:',initialvalue=v.get('name',''),parent=root)
    if name is None:return
    url=simpledialog.askstring('Edit','Spotify track URL:',initialvalue=v.get('spotify',''),parent=root)
    if url is None:return
    mappings[uid]={'name':name.strip() or uid,'spotify':url.strip()};save();refresh_tree();log('Updated '+uid)
def delete_card():
    uid=selected()
    if uid and messagebox.askyesno('Delete',f'Delete {uid}?',parent=root):mappings.pop(uid);save();refresh_tree();log('Deleted '+uid)
def test():
    uid=selected()
    if not uid:return
    def w():
        try:log('Playing '+mappings[uid].get('name',uid));log('Spotify device: '+play(mappings[uid].get('spotify','')))
        except Exception as e:log('Test error: '+str(e))
    threading.Thread(target=w,daemon=True).start()
def auth_click():
    try:authorize();log('Authorization opened in browser.')
    except Exception as e:messagebox.showerror('Spotify',str(e),parent=root)
def toggle_click():
    global control;control=bool(toggle.get());log('RFID control '+('ON' if control else 'OFF'))
def build():
    global root,tree,logbox,toggle
    root=tk.Tk();root.title('RFID → Spotify Desktop');root.geometry('1100x680')
    top=ttk.Frame(root,padding=12);top.pack(fill='x');ttk.Label(top,text='RFID → Spotify',font=('Segoe UI',22,'bold')).pack(side='left')
    toggle=tk.BooleanVar(value=True);ttk.Checkbutton(top,text='RFID CONTROL',variable=toggle,command=toggle_click).pack(side='right')
    b=ttk.Frame(root,padding=(12,0,12,8));b.pack(fill='x')
    for txt,cmd in [('Authorize Spotify',auth_click),('Open Spotify',open_spotify),('Test Selected',test),('+ Add Card',add_card),('Edit',edit_card),('Delete',delete_card)]:ttk.Button(b,text=txt,command=cmd).pack(side='left',padx=4)
    f=ttk.Frame(root,padding=12);f.pack(fill='both',expand=True);tree=ttk.Treeview(f,columns=('UID','Name','Spotify URL'),show='headings');
    for c,w in [('UID',170),('Name',180),('Spotify URL',650)]:tree.heading(c,text=c);tree.column(c,width=w)
    tree.pack(side='left',fill='both',expand=True);s=ttk.Scrollbar(f,orient='vertical',command=tree.yview);s.pack(side='right',fill='y');tree.configure(yscrollcommand=s.set)
    lf=ttk.LabelFrame(root,text='Activity',padding=8);lf.pack(fill='x',padx=12,pady=(0,12));logbox=tk.Text(lf,height=7);logbox.pack(fill='x')
    refresh_tree();log('Server: http://0.0.0.0:5000/rfid');log('Normal playback uses Spotify desktop; browser is only for authorization.')
    return root

if __name__=='__main__':
    threading.Thread(target=server,daemon=True).start();time.sleep(.3);build();root.mainloop()
