# -*- coding: utf-8 -*-
ENV_KEY = 'PYNCMD_SESSION'
def generate_identity(phone,pwd):
    # Generates session data, which contatins everything we'd need
    # to recover a previous login state. No plaintext password is stored here.
    from pyncm import GetCurrentSession
    from pyncm.apis.login import LoginViaCellphone
    try:
        LoginViaCellphone(phone,pwd)
    except Exception as e:
        return 503 , str(e)
    # Unfortunately, Vercel enviorns are limited to sizes below 4KB 
    # and a raw dump would already be larger than that, without encoding overheads
    # Here's some hack I don't really think should be added to PyNCM, but will do for now
    from json import dumps
    from zlib import compress # zlib handled this suprisingly well！(about 0.25x of original size)
    from base64 import b64encode # ~1.2x orignal size
    return 200, b64encode(compress(dumps(GetCurrentSession().dump()).encode())).decode()

def load_identity():    
    # Loads session data from local file 'session'
    # and then tries to restore login state per-request
    from pyncm import SetCurrentSession , Session
    import os        
    if not ENV_KEY in os.environ:
        return print(f'[W] 找不到 {ENV_KEY} 环境变量，以游客模式继续')
    session = os.environ[ENV_KEY]
    from json import loads
    from zlib import decompress
    from base64 import b64decode
    session_obj = Session()
    session_obj.load(loads(decompress(b64decode(session)).decode()))
    if not session_obj.login_info['success']:
        return print('[W] 配置不含有效登录态')
    SetCurrentSession(session_obj)
    print('[I] %s 已登录' % session_obj.login_info['content']['profile']['nickname'])
    return session_obj.login_info['content']['profile']['nickname']

def route(path , query):        
    # The query K-V always comes in [str]-[List[str]]
    query = {k:v if len(v) > 1 else v[0] for k,v in query.items()}
    base , target = query.get('module','?'), query.get('method','?')
    if 'module' in query : del query['module']
    if 'method' in query : del query['method']
    # Pop method descriptors before we actually pass the arguments
    ident_info = load_identity()
    if ident_info is None:
        print('[W] 匿名（游客）身份操作。请参见 README ： https://github.com/mos9527/pyncmd')
    print('[D] PyNCM API Call %s.%s' % (base,target))    
    err = lambda code,msg:{'code' : code , 'message' : msg}
    if base == 'identity':
        if ident_info is None:        
            return err(*generate_identity(query['phone'],query['pwd']))
        else:            
            return err(503,'Session environ "session" non-empty. See https://github.com/mos9527/pyncmd for more info')
    import pyncm,pyncm.apis
    # Filtering request    
    if not base in filter(lambda x:x.islower() and not '_' in x,dir(pyncm.apis)):
        return err(404,'pyncm module %s not found' % base)
    if base in {'user','login','cloud'}:
        return err(403,'pyncm module %s not allowed' % base)
    base = getattr(pyncm.apis,base)
    if not target in filter(lambda x:'Get' in x or 'Set' in x,dir(base)):
        return err(404,'module method %s not found' % target)
    if 'Set' in target:
        return err(403,'"Set" not allowed')
    query = {k:v if not len(v) == 1 else v[0] for k,v in query.items()}
    response = getattr(base,target)(**query)    
    if ident_info:
        response['server'] = ident_info
    return response

from http.server import BaseHTTPRequestHandler
from urllib.parse import unquote,parse_qs,urlparse
from json import dumps
class handler(BaseHTTPRequestHandler):
  def do_GET(self):
    # Parsing query string
    self.scheme, self.netloc, self.path, self.params, self.query, self.fragment = urlparse(self.path)
    self.path = unquote(self.path)
    self.query = parse_qs(self.query)
    try:
        # Success responses are directly routed
        result = route(self.path,self.query)
    except Exception as e:
        # Errors will then be passed as 500s        
        result = {'code':'500','message':'Internal error : %s' % e}    
    self.send_response(int(result.get('code',200)))
    self.send_header('Content-type', 'application/json; charset=utf-8')
    self.end_headers()    
    response = dumps(result,ensure_ascii=False).encode('utf-8')
    self.wfile.write(response)
