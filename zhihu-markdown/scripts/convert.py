#!/usr/bin/env python3
"""convert.py — 知乎页面 HTML → Markdown 转换器（回答页 / 专栏文章页自动识别）

用法:
  python3 convert.py <input.html> [--out-dir DIR] [--slug NAME] [--answer-id ID]
                     [--keep-remote-images] [--no-verify]

输入: fetch.sh 抓取的完整页面 DOM
输出: <out-dir>/<slug>.md + <slug>.assets/image-N.jpg（图片本地化，绕过防盗链）

页面结构要点（排查问题时参考）:
  回答页: div.AnswerItem[data-zop] → .RichContent-inner → span.RichText[itemprop=text]
          data-zop 含 authorName/itemId(回答id)/title(问题标题)/type
          元信息: 答答项内 meta[itemprop=upvoteCount|dateCreated|dateModified]
          折叠态(RichContent-inner--collapsed)不影响, 完整正文仍在 DOM 里
  文章页: h1.Post-Title + div.Post-RichTextContainer(内容直接子元素)
          元信息: meta[itemprop=datePublished|commentCount],
                 itemprop=author 容器内 meta[itemprop=name|url|zhihu:followerCount],
                 button.VoteButton[aria-label="赞同 N"]
"""
import argparse
import json
import os
import re
import sys
import html as htmlmod
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import Request, urlopen
from lxml import etree

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
REFERER = 'https://www.zhihu.com/'


def text_of(el):
    return ''.join(el.itertext())


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', help='抓取的页面 HTML 文件')
    ap.add_argument('--out-dir', default='.', help='输出目录（默认当前目录）')
    ap.add_argument('--slug', help='输出文件名（不含 .md；默认 知乎<类型>_<作者>_<标题片段>）')
    ap.add_argument('--answer-id', help='回答 ID（URL 含 /answer/<id> 时用于精确定位）')
    ap.add_argument('--keep-remote-images', action='store_true',
                    help='不下载图片，保留远程链接（会因防盗链裂图）')
    ap.add_argument('--no-verify', action='store_true', help='跳过完整性校验')
    return ap.parse_args()


# ---------------- 链接清洗 ----------------
def clean_href(href):
    """解包知乎跳转链接；返回 None 表示丢弃该链接（zhida 自动实体链接）。"""
    if not href:
        return None
    if href.startswith('/'):
        href = 'https://www.zhihu.com' + href
    if href.startswith('https://zhida.zhihu.com/search'):
        return None  # 知乎自动加的实体链接，纯噪声
    if href.startswith('https://link.zhihu.com/?'):
        try:
            q = parse_qs(urlparse(href).query)
            if 'target' in q:
                return unquote(q['target'][0])
        except Exception:
            pass
    return href


# ---------------- 图片 ----------------
class ImageStore:
    def __init__(self, assets_dir_name, keep_remote=False):
        self.urls = []
        self.assets_dir_name = assets_dir_name
        self.keep_remote = keep_remote
        self.failures = []

    def register(self, url):
        if not url:
            return None
        if url in self.urls:
            return self.urls.index(url) + 1
        self.urls.append(url)
        return len(self.urls)

    def local_ref(self, idx):
        return f'{self.assets_dir_name}/image-{idx}.jpg'

    def download_all(self, out_dir):
        if self.keep_remote or not self.urls:
            return
        assets_dir = os.path.join(out_dir, self.assets_dir_name)
        os.makedirs(assets_dir, exist_ok=True)
        for i, url in enumerate(self.urls, 1):
            path = os.path.join(assets_dir, f'image-{i}.jpg')
            if os.path.exists(path) and os.path.getsize(path) > 0:
                continue
            try:
                req = Request(url, headers={'Referer': REFERER, 'User-Agent': UA})
                with urlopen(req, timeout=30) as r:
                    data = r.read()
                with open(path, 'wb') as f:
                    f.write(data)
            except Exception as e:
                self.failures.append((i, url, str(e)))

    def markdown_ref(self, idx, caption=''):
        url = self.urls[idx - 1]
        label = caption or '图片'
        if self.keep_remote or (idx, ) in () or any(f[0] == idx for f in self.failures):
            return f'![{label}]({url})'
        return f'![{label}]({self.local_ref(idx)})'


def best_img_url(el):
    """从 figure/noscript/img 中选最佳图片 URL（优先原图 data-original）。"""
    for attr in ('data-original', 'data-actualsrc', 'src'):
        u = el.get(attr)
        if u:
            return u
    return ''


# ---------------- 行内转换 ----------------
MATHJAX_SKIP = ('MathJax_Preview', 'MathJax_SVG', 'MJX_Assistive')


def inline(el, store):
    parts = []
    if el.text:
        parts.append(el.text)
    for child in el:
        tag = child.tag if isinstance(child.tag, str) else ''
        cls = child.get('class') or ''
        if tag in ('b', 'strong'):
            t = inline(child, store).strip()
            parts.append(f'**{t}**' if t else '')
        elif tag in ('i', 'em'):
            t = inline(child, store).strip()
            parts.append(f'*{t}*' if t else '')
        elif tag == 'a':
            t = inline(child, store).strip()
            href = clean_href(child.get('href'))
            parts.append(f'[{t}]({href})' if (t and href) else t)
        elif tag == 'br':
            parts.append('\n')
        elif tag == 'code':
            t = text_of(child)
            parts.append(f'`{t}`' if t and '\n' not in t else t)
        elif tag == 'span' and 'ztext-math' in cls:
            # LaTeX 源在 data-tex 属性；跳过 MathJax 渲染内部节点（否则文字重复）
            tex = child.get('data-tex') or ''
            if tex:
                parts.append(f'${tex}$')
        elif tag == 'math':
            t = ' '.join(text_of(child).split())
            parts.append(f'${t}$' if t else '')
        elif tag == 'svg':
            pass  # 图标
        elif tag == 'img':
            src = best_img_url(child)
            if src:
                idx = store.register(src)
                if idx:
                    parts.append(store.markdown_ref(idx))
        elif tag == 'noscript':
            pass  # 知乎用 noscript 存原图，已由 best_img_url 处理
        else:
            if any(k in cls for k in MATHJAX_SKIP):
                pass
            else:
                parts.append(inline(child, store))
        if child.tail:
            parts.append(child.tail)
    return ''.join(parts)


def detect_lang(code):
    if re.search(r'torch::|template\s*<|__global__|__device__|__shared__|#include|float4|dim3\b|cudaMalloc|PackedTensorAccessor', code):
        return 'cpp'
    if re.search(r'^\s*(from\s+\S+\s+import|import\s+\S+|def\s+\w+\()', code, re.M):
        return 'python'
    return ''


# ---------------- 块级转换 ----------------
def convert(el, out, store):
    tag = el.tag if isinstance(el.tag, str) else ''
    cls = el.get('class') or ''
    if tag == 'p':
        if 'ztext-empty-paragraph' in cls:
            return
        t = inline(el, store).strip()
        if t:
            out.append(t)
            out.append('')
    elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        t = inline(el, store).strip()
        if t:
            out.append('#' * min(int(tag[1]) + 1, 6) + ' ' + t)
            out.append('')
    elif tag == 'figure':
        url = ''
        for img in el.iter('img'):
            url = best_img_url(img)
            if url:
                break
        caption = ''
        for fc in el.iter('figcaption'):
            c = ' '.join(text_of(fc).split())
            if c and c != '在这里插入图片描述':  # 作者编辑器占位符
                caption = c
        if url:
            idx = store.register(url)
            if idx:
                out.append(store.markdown_ref(idx, caption))
                out.append('')
    elif tag == 'blockquote':
        # 知乎 blockquote 常为纯文本节点（无子元素），必须取 el 自身文本
        t = ' '.join(inline(el, store).split())
        if t:
            out.append('> ' + t)
            out.append('')
    elif tag == 'ul':
        def render_ul(e, indent):
            prefix = '  ' * indent
            for sub in e:
                stag = sub.tag if isinstance(sub.tag, str) else ''
                if stag == 'li':
                    nested = [c for c in sub if (c.tag if isinstance(c.tag, str) else '') == 'ul']
                    t = inline(sub, store).strip()
                    if t:
                        out.append(prefix + '- ' + ' '.join(t.split('\n')))
                    for n in nested:
                        render_ul(n, indent + 1)
                elif stag == 'ul':
                    # 知乎编辑器把嵌套列表平铺为 ul 的直接子元素（不在 li 内）
                    render_ul(sub, indent + 1)
        render_ul(el, 0)
        out.append('')
    elif tag == 'ol':
        def render_ol(e, indent):
            n = 0
            for sub in e:
                stag = sub.tag if isinstance(sub.tag, str) else ''
                if stag == 'li':
                    n += 1
                    t = inline(sub, store).strip()
                    if t:
                        out.append(f'{"  " * indent}{n}. ' + ' '.join(t.split('\n')))
                elif stag == 'ol':
                    render_ol(sub, indent + 1)
                elif stag == 'ul':
                    for s2 in sub:
                        if (s2.tag if isinstance(s2.tag, str) else '') == 'li':
                            t2 = inline(s2, store).strip()
                            if t2:
                                out.append('  ' * (indent + 1) + '- ' + ' '.join(t2.split('\n')))
        render_ol(el, 0)
        out.append('')
    elif tag == 'hr':
        out.append('---')
        out.append('')
    elif tag == 'pre':
        code = text_of(el).rstrip('\n')
        out.append(f'```{detect_lang(code)}')
        out.append(code)
        out.append('```')
        out.append('')
    elif tag in ('script', 'style', 'svg'):
        pass
    else:
        for sub in el:
            convert(sub, out, store)


# ---------------- 元数据提取 ----------------
def collect_meta(root):
    """返回 dict: title, author, author_url, followers, votes, comments, created, modified, url"""
    meta = {}
    m = root.xpath('//h1[contains(@class,"Post-Title")]')
    if m:
        meta['title'] = ' '.join(text_of(m[0]).split())
    def itemprop(name, scope=None):
        xp = f'.//meta[@itemprop="{name}"]' if scope is not None else f'//meta[@itemprop="{name}"]'
        r = (scope if scope is not None else root).xpath(xp)
        return r[0].get('content') if r else None
    meta['created'] = itemprop('datePublished') or itemprop('dateCreated')
    meta['modified'] = itemprop('dateModified')
    meta['comments'] = itemprop('commentCount')
    # 作者容器（itemprop=author 的元素内）
    for c in root.iter():
        if isinstance(c.tag, str) and c.get('itemprop') == 'author':
            meta['author'] = itemprop('name', c) or ''
            meta['author_url'] = itemprop('url', c) or ''
            fw = itemprop('zhihu:followerCount', c)
            if fw:
                try:
                    meta['followers'] = int(fw)
                except ValueError:
                    pass
            break
    for b in root.xpath('//button[contains(@class,"VoteButton")]'):
        mm = re.search(r'赞同\s*(\d+)', b.get('aria-label') or '')
        if mm:
            meta['votes'] = mm.group(1)
            break
    return meta


def answer_meta(root, answer_id):
    """回答页元数据: 定位 AnswerItem[data-zop]。"""
    target = None
    for item in root.iter('div'):
        zop = item.get('data-zop')
        if not zop:
            continue
        try:
            z = json.loads(htmlmod.unescape(zop))
        except (ValueError, TypeError):
            continue
        if z.get('type') != 'answer':
            continue
        if answer_id and str(z.get('itemId')) != str(answer_id):
            continue
        target, tz = item, z
        break
    if target is None:
        return None, None
    meta = {
        'title': tz.get('title', ''),
        'author': tz.get('authorName', ''),
        'answer_id': tz.get('itemId'),
    }
    for m in target.iter('meta'):
        p = m.get('itemprop')
        if p == 'upvoteCount':
            meta['votes'] = m.get('content')
        elif p == 'dateCreated':
            meta['created'] = m.get('content')
        elif p == 'dateModified':
            meta['modified'] = m.get('content')
    inner = target.xpath('.//div[contains(@class,"RichContent-inner")]')
    if not inner:
        return None, None
    rich = inner[0].xpath('.//span[contains(@class,"RichText") and @itemprop="text"]')
    container = rich[0] if rich else inner[0]
    meta['url'] = f"https://www.zhihu.com/question/…/answer/{meta['answer_id']}"
    return meta, container


def article_container(root):
    c = root.xpath('//div[contains(@class,"Post-RichTextContainer")]')
    return c[0] if c else None


# ---------------- 校验 ----------------
def clean_text(el):
    """与 inline() 同口径的纯文本（无 markdown 标记），用于完整性比对。"""
    parts = []
    if el.text:
        parts.append(el.text)
    for child in el:
        tag = child.tag if isinstance(child.tag, str) else ''
        cls = child.get('class') or ''
        if tag == 'span' and 'ztext-math' in cls:
            parts.append(child.get('data-tex') or '')
        elif tag in ('svg', 'noscript', 'br') or any(k in cls for k in MATHJAX_SKIP):
            pass
        else:
            parts.append(clean_text(child))
        if child.tail:
            parts.append(child.tail)
    return ''.join(parts)


def verify(container, md):
    """检查所有 p/li/h2/h3/blockquote 的文本都出现在 md 中。返回 (缺失数, 详情)。"""
    md_norm = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', md)
    for ch in ('**', '`', '$'):
        md_norm = md_norm.replace(ch, '')
    md_norm = re.sub(r'\s+', '', md_norm)

    missing = []
    for el in container.iter():
        tag = el.tag if isinstance(el.tag, str) else ''
        if tag not in ('p', 'li', 'h2', 'h3', 'blockquote'):
            continue
        t = re.sub(r'\s+', '', clean_text(el))
        if len(t) >= 8 and t not in md_norm:
            missing.append(f'<{tag}> {clean_text(el)[:50]}')
    return len(missing), missing


# ---------------- 主流程 ----------------
def sanitize(s, maxlen=40):
    s = re.sub(r'[/\\:*?"<>|\r\n]', '', s).strip()
    return s[:maxlen].strip()


def fmt_date(iso):
    m = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})', iso or '')
    if not m:
        return iso or ''
    try:
        h = int(m.group(2))
        return f'{m.group(1)} {h}:{m.group(3)} UTC（北京时间 {h + 8}:{m.group(3)}）'
    except ValueError:
        return iso


def main():
    args = parse_args()
    parser = etree.HTMLParser(encoding='utf-8')
    tree = etree.parse(args.input, parser)
    root = tree.getroot()

    # 页面类型识别
    mode = meta = container = None
    if article_container(root) is not None and root.xpath('//h1[contains(@class,"Post-Title")]'):
        mode = 'article'
        container = article_container(root)
        meta = collect_meta(root)
        meta.setdefault('url', '')
    else:
        aid = args.answer_id
        if not aid:
            m = re.search(r'/answer/(\d+)', args.input + ' ' + (meta or {}).get('url', ''))
            aid = m.group(1) if m else None
        meta, container = answer_meta(root, aid)
        if container is not None:
            mode = 'answer'
    if mode is None:
        print('ERROR: 无法识别页面类型（既不是专栏文章也不是回答页）。'
              '可能是登录墙/验证页/风控页，检查输入 HTML。', file=sys.stderr)
        sys.exit(2)

    type_label = '专栏' if mode == 'article' else '回答'
    slug = args.slug or sanitize(
        f"知乎{type_label}_{meta.get('author', '')}_{meta.get('title', '')}")
    assets_name = sanitize(slug, 100) + '.assets'
    store = ImageStore(assets_name, keep_remote=args.keep_remote_images)

    # 转换正文
    out = []
    for sub in container:
        convert(sub, out, store)
    md_body = '\n'.join(out)
    md_body = re.sub(r'\n{3,}', '\n\n', md_body).strip()

    # 元信息头
    meta_lines = [f"# {meta.get('title', '')}", '']
    author = meta.get('author', '')
    author_url = meta.get('author_url', '')
    followers = meta.get('followers')
    if author:
        author_str = f'[{author}]({author_url})' if author_url else author
        if followers:
            author_str += f'（{followers:,} 关注者）'
        meta_lines.append(f'> **作者**：{author_str}')
    if meta.get('created'):
        meta_lines.append(f"> **发布时间**：{fmt_date(meta['created'])}")
    if meta.get('modified') and meta['modified'] != meta.get('created'):
        meta_lines.append(f"> **更新时间**：{fmt_date(meta['modified'])}")
    stats = []
    if meta.get('votes'):
        stats.append(f"**赞同数**：{meta['votes']}")
    if meta.get('comments'):
        stats.append(f"**评论数**：{meta['comments']}")
    if stats:
        meta_lines.append('> ' + '　'.join(stats))
    if meta.get('url'):
        meta_lines.append(f"> **原文链接**：[{meta['url']}]({meta['url']})")
    header = '\n'.join(meta_lines) + '\n\n---\n\n'

    doc = header + md_body + '\n'

    # 写出 + 下载图片
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, slug + '.md')
    store.download_all(out_dir)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(doc)

    # 校验
    miss_n, missing = (0, []) if args.no_verify else verify(container, doc)

    print(f'mode:        {mode}')
    print(f'title:       {meta.get("title", "")}')
    print(f'author:      {author}')
    print(f'output:      {md_path}')
    print(f'images:      {len(store.urls)} downloaded'
          + (f', FAILED: {store.failures}' if store.failures else ''))
    print(f'code blocks: {md_body.count("```") // 2}')
    print(f'verify:      {"PASS (0 missing)" if miss_n == 0 else f"FAIL ({miss_n} missing)"}')
    for mline in missing[:10]:
        print(f'  missing: {mline}')
    sys.exit(0 if (miss_n == 0 and not store.failures) else 3)


if __name__ == '__main__':
    main()
