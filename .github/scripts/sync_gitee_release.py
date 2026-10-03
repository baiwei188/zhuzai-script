#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步 主宰世界脚本.exe 到 gitee release v_latest（客户端从 gitee 下载）。
由 GitHub Actions 自动调用；固定 tag v_latest。
v2 改进：
1. 幂等：附件已存在且大小一致 → 直接成功退出（不重复删建）
2. 失败保护：上传到临时 tag，成功后才切换 v_latest；失败保留旧 release（客户端下载不断流）
3. 单次上传超时加大到 3600s
"""
import os, sys, json, uuid, urllib.request, urllib.parse

TOKEN = os.environ.get('GITEE_TOKEN', '')
OWNER, REPO = 'baiwei168', 'zhuzai-script'
EXE = '主宰世界脚本.exe'
TAG = 'v_latest'
BASE = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}'
HDR = {'User-Agent': 'doubao-workflow/2.0'}


def api(url, method='GET', form=None, timeout=3600, raw_body=None, ctype=None):
    data = None
    h = dict(HDR)
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h['Content-Type'] = 'application/x-www-form-urlencoded'
    if raw_body is not None:
        data = raw_body
        h['Content-Type'] = ctype
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, (json.loads(body.decode()) if body else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'ignore')[:300]
    except Exception as e:
        return -1, str(e)


def find_release(tag):
    st, lst = api(BASE + f'/releases?per_page=100&access_token={TOKEN}')
    if isinstance(lst, list):
        for it in lst:
            if it.get('tag_name') == tag:
                return it
    return None


def list_attaches(rid):
    st, files = api(BASE + f'/releases/{rid}/attach_files?per_page=50&access_token={TOKEN}')
    return files if isinstance(files, list) else []


def main():
    if not TOKEN:
        print('GITEE_TOKEN missing')
        sys.exit(1)
    if not os.path.exists(EXE):
        print('exe not found:', EXE)
        sys.exit(1)
    want_sz = os.path.getsize(EXE)
    # 1) 幂等：v_latest 附件已是最新 → 直接成功（不删建、不重复上传）
    rel = find_release(TAG)
    if rel:
        for f in list_attaches(rel['id']):
            if f.get('name') == EXE and f.get('size') == want_sz:
                print('已是最新，跳过（附件 size=%s）' % f.get('size'))
                return 0
    # 2) 上传到临时 tag（失败不碰旧 release，客户端不断流）
    tmp_tag = 'v_tmp_' + uuid.uuid4().hex[:8]
    st, d = api(BASE + f'/releases?access_token={TOKEN}', 'POST',
                {'tag_name': tmp_tag, 'name': 'tmp sync', 'body': 'temp',
                 'target_commitish': 'main'})
    rid = d.get('id') if isinstance(d, dict) else None
    if not rid:
        print('创建临时 release 失败:', st, d)
        sys.exit(1)
    boundary = '----zz' + uuid.uuid4().hex
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{EXE}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode('utf-8')
    tail = f'\r\n--{boundary}--\r\n'.encode('utf-8')
    with open(EXE, 'rb') as f:
        body_all = head + f.read() + tail
    print('上传 %s 到临时 release %s ...' % (EXE, rid))
    st, d = api(BASE + f'/releases/{rid}/attach_files?access_token={TOKEN}',
                'POST', raw_body=body_all,
                ctype=f'multipart/form-data; boundary={boundary}', timeout=3600)
    if not (isinstance(d, dict) and d.get('id')):
        print('上传失败，保留旧 release（客户端不受影响）:', st, d)
        api(BASE + f"/releases/{rid}?access_token={TOKEN}", 'DELETE')
        sys.exit(1)
    print('上传成功 size=%s' % d.get('size'))
    # 3) 切换：删旧 v_latest → 临时 release 改名为 v_latest（客户端 URL 恒定不变）
    if rel:
        api(BASE + f"/releases/{rel['id']}?access_token={TOKEN}", 'DELETE')
        print('已删除旧 release', rel['id'])
    st, d = api(BASE + f'/releases/{rid}?access_token={TOKEN}', 'PATCH',
                {'tag_name': TAG, 'name': 'latest client', 'body': 'auto synced from GitHub'})
    print('切换完成 status=%s' % st)
    print('download=', f'https://gitee.com/{OWNER}/{REPO}/releases/download/{TAG}/' + urllib.parse.quote(EXE))
    return 0


if __name__ == '__main__':
    sys.exit(main())
