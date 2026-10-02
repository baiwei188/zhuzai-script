#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步 主宰世界脚本.exe 到 gitee release v_latest（客户端从 gitee 下载）。
由 GitHub Actions 自动调用；固定 tag v_latest，附件每次覆盖重建。"""
import os, sys, json, uuid, urllib.request, urllib.parse

TOKEN = os.environ.get('GITEE_TOKEN', '')
OWNER, REPO = 'baiwei168', 'zhuzai-script'
EXE = '主宰世界脚本.exe'
TAG = 'v_latest'
BASE = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}'
HDR = {'User-Agent': 'doubao-workflow/1.0'}

def api(url, method='GET', form=None, timeout=120):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    h = dict(HDR)
    if data is not None:
        h['Content-Type'] = 'application/x-www-form-urlencoded'
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, (json.loads(body.decode()) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'ignore')[:300]

def main():
    if not TOKEN:
        print('GITEE_TOKEN missing')
        sys.exit(1)
    if not os.path.exists(EXE):
        print('exe not found:', EXE)
        sys.exit(1)
    # 1) 删除同名旧 release（附件随 release 删除）
    st, lst = api(BASE + f'/releases?per_page=100&access_token={TOKEN}')
    if isinstance(lst, list):
        for it in lst:
            if it.get('tag_name') == TAG:
                api(BASE + f"/releases/{it['id']}?access_token={TOKEN}", 'DELETE')
                print('deleted old release', it.get('id'))
    # 2) 创建 release
    st, d = api(BASE + f'/releases?access_token={TOKEN}', 'POST',
                {'tag_name': TAG, 'name': 'latest client',
                 'body': 'auto synced from GitHub', 'target_commitish': 'main'})
    rid = d.get('id') if isinstance(d, dict) else None
    if not rid:
        print('create release failed:', st, d)
        sys.exit(1)
    print('release created id=', rid)
    # 3) 上传附件（multipart）
    boundary = '----zz' + uuid.uuid4().hex
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{EXE}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode('utf-8')
    tail = f'\r\n--{boundary}--\r\n'.encode('utf-8')
    with open(EXE, 'rb') as f:
        body_all = head + f.read() + tail
    req = urllib.request.Request(BASE + f'/releases/{rid}/attach_files?access_token={TOKEN}',
                                 data=body_all,
                                 headers={**HDR, 'Content-Type': f'multipart/form-data; boundary={boundary}'},
                                 method='POST')
    with urllib.request.urlopen(req, timeout=1200) as r:
        res = json.loads(r.read().decode())
    print('attach ok id=', res.get('id'), 'size=', res.get('size'))
    print('download=', f'https://gitee.com/{OWNER}/{REPO}/releases/download/{TAG}/' + urllib.parse.quote(EXE))

if __name__ == '__main__':
    main()
