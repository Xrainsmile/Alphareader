#!/usr/bin/env python3
"""
AlphaReader 全量令牌化 - 圆角批次（批次 3）
用法：
  python3 tokenize_radius.py --dry-run
  python3 tokenize_radius.py --apply
  python3 tokenize_radius.py --apply --file pages/reports/index.vue

原则：
  1. rpx 值只替换为 --radius-r-* （移动端档），px 值只替换为 --radius-p-* （PC 档）
     严格避免单位混用
  2. 就近收敛：低频散值映射到最接近的刻度
  3. 不覆盖现有 rem 圆角令牌（--radius-sm/md/lg/pill 保持不动）
  4. 自动 .bak 备份
"""
import re, os, sys, argparse, shutil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'src')

# rpx 档映射（就近收敛低频值）
RADIUS_RPX = {
    '2rpx': '--radius-r-xs', '3rpx': '--radius-r-xs', '4rpx': '--radius-r-xs',
    '6rpx': '--radius-r-sm', '5rpx': '--radius-r-sm', '7rpx': '--radius-r-sm',
    '8rpx': '--radius-r-md',
    '10rpx': '--radius-r-md', '12rpx': '--radius-r-md',
    '14rpx': '--radius-r-md', '16rpx': '--radius-r-md',
    '18rpx': '--radius-r-2xl', '20rpx': '--radius-r-2xl',
    '24rpx': '--radius-r-3xl', '22rpx': '--radius-r-3xl',
    '32rpx': '--radius-r-4xl', '36rpx': '--radius-r-4xl',
    '999rpx': '--radius-r-full',
}

# px 档映射
RADIUS_PX = {
    '2px': '--radius-p-sm', '3px': '--radius-p-xs', '4px': '--radius-p-sm',
    '5px': '--radius-p-md', '6px': '--radius-p-md', '7px': '--radius-p-lg',
    '8px': '--radius-p-lg', '9px': '--radius-p-xl',
    '10px': '--radius-p-xl', '12px': '--radius-p-2xl',
    '14px': '--radius-p-3xl', '16px': '--radius-p-4xl',
    '18px': '--radius-p-5xl', '20px': '--radius-p-5xl',
    '999px': '--radius-p-full',
}

def collect_files(only=None):
    files = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in ('node_modules', 'dist', '.git')]
        for f in fn:
            if f.endswith(('.vue', '.css')) and f != 'App.vue':
                p = os.path.join(dp, f)
                if only and not p.endswith(only):
                    continue
                files.append(p)
    return files

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--file', default=None)
    args = ap.parse_args()
    if not args.dry_run and not args.apply:
        ap.error('必须指定 --dry-run 或 --apply')

    files = collect_files(args.file)
    grand = 0

    for p in files:
        src = open(p, encoding='utf-8').read()
        orig = src
        cnt = 0

        # 先处理 rpx（更具体，避免被 px 规则误伤）
        for val, tok in RADIUS_RPX.items():
            pat = re.compile(r'(border-radius:\s*)' + re.escape(val) + r'\b')
            src, n = pat.subn(rf'\1var({tok})', src)
            cnt += n

        # 再处理 px
        for val, tok in RADIUS_PX.items():
            pat = re.compile(r'(border-radius:\s*)' + re.escape(val) + r'\b')
            src, n = pat.subn(rf'\1var({tok})', src)
            cnt += n

        if src != orig:
            grand += cnt
            rel = os.path.relpath(p, ROOT)
            if args.apply:
                shutil.copy2(p, p + '.bak')
                open(p, 'w', encoding='utf-8').write(src)
                print(f'[APPLIED] {rel}: {cnt} 处')
            else:
                print(f'[DRY-RUN] {rel}: {cnt} 处')

    print(f'\n总计: {grand} 处圆角替换, {len(files)} 个文件')

if __name__ == '__main__':
    main()
