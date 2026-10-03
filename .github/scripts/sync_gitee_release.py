#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步 GitHub release 附件（主宰世界脚本.exe + engine.zip）到 gitee release v_latest。
由 GitHub Actions 自动调用（push exe / release published / workflow_dispatch）。
v3 通用化：
1. 从 GitHub release v_latest 附件下载需要同步的文件
2. 幂等：gitee 附件已存在且大小一致 → 跳过
3. 失败保护：上传到临时 tag，全部成功后才切换 v_latest（客户端下载不断流）
4. 多文件（exe + engine.zip）一起切换，保证 release 完整
"""
import os, sys, json, uuid, urllib.request, urllib.parse, tempfile, shutil

GITEE_TOKEN = os.environ.get('GITEE_TOKEN', '')
GH_TOKEN = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN', '')
GH_OWNER, GH_REPO = 'baiwei188', 'zhuzai-script'
OWNER, REPO = 'baiwei168', 'zhuzai-script'
TAG = 'v_latest'
FILES = ['主宰世界脚本.exe', 'engine.zip']
BASE = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}'
HDR = {'User-Agent': 'doubao-workflow/3.0'}


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


def gh_json(url):
    req = urllib.request.Request(url, headers={'Authorization': 'token ' + GH_TOKEN,
                                               'User-Agent': 'doubao'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode('utf-8', 'ignore'))


def gh_download(url, local):
    req = urllib.request.Request(url, headers={'Authorization': 'token ' + GH_TOKEN,
                                               'User-Agent': 'doubao',
                                               'Accept': 'application/octet-stream'})
    with urllib.request.urlopen(req, timeout=3600) as r, open(local, 'wb') as f:
        shutil.copyfileobj(r, f, 65536)


def find_release(tag):
    st, lst = api(BASE + f'/releases?per_page=100&access_token={GITEE_TOKEN}')
    if isinstance(lst, list):
        for it in lst:
            if it.get('tag_name') == tag:
                return it
    return None


def list_attaches(rid):
    st, files = api(BASE + f'/releases/{rid}/attach_files?per_page=50&access_token={GITEE_TOKEN}')
    return files if isinstance(files, list) else []


def main():
    if not GITEE_TOKEN or not GH_TOKEN:
        print('GITEE_TOKEN or GH_TOKEN missing')
        sys.exit(1)
    # 1) 从 GitHub release v_latest 下载附件
    try:
        rel = gh_json(f'https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/releases/tags/{TAG}')
    except Exception as e:
        print('GitHub release 读取失败:', str(e)[:200])
        sys.exit(1)
    assets = {a['name']: a for a in rel.get('assets', [])}
    tmp = tempfile.mkdtemp(prefix='gitee_sync_')
    pending = {}
    for fn in FILES:
        if fn not in assets:
            print('GitHub release 无附件，跳过:', fn)
            continue
        local = os.path.join(tmp, fn)
        try:
            gh_download(assets[fn]['browser_download_url'], local)
            pending[fn] = local
            print('已从 GitHub 下载:', fn, round(os.path.getsize(local) / 1048576, 1), 'MB')
        except Exception as e:
            print('下载失败:', fn, str(e)[:150])
    if not pending:
        print('没有待同步文件')
        return 0
    # 2) 幂等检查 gitee v_latest 已有附件
    grel = find_release(TAG)
    gatt = {}
    if grel:
        for f in list_attaches(grel['id']):
            gatt[f.get('name')] = f.get('size')
    need = {}
    for fn, local in pending.items():
        sz = os.path.getsize(local)
        if gatt.get(fn) == sz:
            print(fn, 'gitee 已是最新，跳过')
            continue
        need[fn] = local
    if not need:
        print('全部附件已是最新')
        return 0
    # 3) 上传到临时 release（全部成功后切换，失败保留旧 release）
    tmp_tag = 'v_tmp_' + uuid.uuid4().hex[:8]
    st, d = api(BASE + f'/releases?access_token={GITEE_TOKEN}', 'POST',
                {'tag_name': tmp_tag, 'name': 'tmp sync', 'body': 'temp',
                 'target_commitish': 'main'})
    rid = d.get('id') if isinstance(d, dict) else None
    if not rid:
        print('创建临时 release 失败:', st, d)
        sys.exit(1)
    for fn, local in need.items():
        boundary = '----zz' + uuid.uuid4().hex
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{fn}"\r\n'
                f'Content-Type: application/octet-stream\r\n\r\n').encode('utf-8')
        tail = f'\r\n--{boundary}--\r\n'.encode('utf-8')
        with open(local, 'rb') as f:
            body_all = head + f.read() + tail
        print('上传 %s 到临时 release ...' % fn)
        st, d = api(BASE + f'/releases/{rid}/attach_files?access_token={GITEE_TOKEN}',
                    'POST', raw_body=body_all,
                    ctype=f'multipart/form-data; boundary={boundary}', timeout=3600)
        if not (isinstance(d, dict) and d.get('id')):
            print('上传失败，保留旧 release（客户端不受影响）:', st, d)
            api(BASE + f"/releases/{rid}?access_token={GITEE_TOKEN}", 'DELETE')
            sys.exit(1)
        print(fn, '上传成功 size=%s' % d.get('size'))
    # 4) 切换：删旧 v_latest → 临时 release 改名为 v_latest（客户端 URL 恒定）
    if grel:
        api(BASE + f"/releases/{grel['id']}?access_token={GITEE_TOKEN}", 'DELETE')
        print('已删除旧 release', grel['id'])
    st, d = api(BASE + f'/releases/{rid}?access_token={GITEE_TOKEN}', 'PATCH',
                {'tag_name': TAG, 'name': 'latest client', 'body': 'auto synced from GitHub'})
    print('切换完成 status=%s' % st)
    print('同步附件:', list(need.keys()))
    print('download=', f'https://gitee.com/{OWNER}/{REPO}/releases/download/{TAG}/' + urllib.parse.quote(need.popitem()[0]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
