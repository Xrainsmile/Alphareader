#!/usr/bin/env python3
"""AlphaReader 核心模块英文替换（任务二）

安全约束（重要，避免误伤）：
  1. 只替换 <script 之前的模板区，不动 JS 逻辑中的字符串
  2. 跳过 <!-- --> 注释，避免把注释翻成英文导致中英混杂
  3. 只替换 >文案< 与 placeholder="..." 两种可见形态
  4. 不碰 :class / :style / 事件绑定等属性值
  5. 自动 .bak 备份，--dry-run 预演

用法：
  python3 apply_i18n.py --dry-run
  python3 apply_i18n.py --apply
"""
import re, os, json, argparse, shutil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'src')
MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'i18n_core.json')

TARGETS = [
    'pages/index/index.vue',
    'pages/reports/index.vue',
    'pages/reports/detail.vue',
    'pages/briefing/detail.vue',
    'components/common/EmptyState.vue',
    'components/common/GateButton.vue',
    'components/common/SiteFooter.vue',
    'components/news/NewsCard.vue',
    'components/news/NewsCardGroup.vue',
    'components/news/NewsSearchBar.vue',
    'components/news/NewsFilterPopover.vue',
    'components/news/TickerOverlay.vue',
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--apply', action='store_true')
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error('must specify --dry-run or --apply')

    pairs = json.load(open(MAP_PATH, encoding='utf-8'))
    # 长文案优先，避免短串先命中导致长串残留
    ordered = sorted(pairs.items(), key=lambda kv: -len(kv[0]))

    grand, missed_total = 0, set()
    for rel in TARGETS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        src = open(p, encoding='utf-8').read()
        # 切模板区：只处理 <script 之前
        idx = src.find('<script')
        head, sep, tail = (src[:idx], '<script', src[idx + 7:]) if idx >= 0 else (src, '', '')

        # 保护注释：占位后还原
        comments = []

        def _stash(m):
            comments.append(m.group(0))
            return f'\x00C{len(comments) - 1}\x00'

        head = re.sub(r'<!--.*?-->', _stash, head, flags=re.S)

        cnt = 0
        for cn, en in ordered:
            cn_unesc = cn.replace('&lt;', '<')
            en_esc = en.replace('<', '&lt;')
            # 形态1: >中文<
            head, n1 = re.subn(r'>' + re.escape(cn) + r'<', '>' + en + '<', head)
            head, n1b = re.subn(r'>' + re.escape(cn_unesc) + r'<', '>' + en_esc + '<', head)
            # 形态2: placeholder="中文"
            head, n2 = re.subn(
                r'(placeholder=")' + re.escape(cn) + r'(")', r'\g<1>' + en + r'\g<2>', head)
            cnt += n1 + n1b + n2

        # 还原注释
        def _restore(m):
            return comments[int(m.group(1))]

        head = re.sub(r'\x00C(\d+)\x00', _restore, head)

        if cnt:
            grand += cnt
            if args.apply:
                shutil.copy2(p, p + '.bak')
                open(p, 'w', encoding='utf-8').write(head + sep + tail)
                print(f'[APPLIED] {rel}: {cnt}')
            else:
                print(f'[DRY-RUN] {rel}: {cnt}')

        # 残留检测
        tmpl = re.sub(r'<!--.*?-->', '', head, flags=re.S)
        for h in re.findall(r'>([^<>{}]*[\u4e00-\u9fff][^<>{}]*)<', tmpl):
            h = h.strip()
            if h and not re.match(r'^[\s:;\-\d\.rpx#%]+$', h):
                missed_total.add((rel, h))

    print(f'\nTotal replaced: {grand}')
    if missed_total:
        print('\nResidual Chinese (needs manual mapping):')
        for rel, h in sorted(missed_total):
            print(f'  {rel}: {h}')
    else:
        print('No residual Chinese in target templates.')


if __name__ == '__main__':
    main()
