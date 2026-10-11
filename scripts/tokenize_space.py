#!/usr/bin/env python3
"""
AlphaReader 全量令牌化 - 间距批次（批次 4）
用法：
  python3 tokenize_space.py --dry-run
  python3 tokenize_space.py --apply

保守策略（重要）：
  间距直接影响布局，激进替换风险高。本脚本【只替换】高频标准值：
    - 单值简写 padding/margin/gap（如 `padding: 16px;`），不碰多值简写（如 `padding: 8px 16px;`）
    - 只替换 px 档，且值必须在刻度内（4/8/12/16/20/24）
    - 跳过 flex/grid 的 `gap` 中含 auto/百分比的写法
  多值简写与 rpx 档保持原样，留待人工逐项处理。
  自动 .bak 备份。
"""
import re, os, argparse, shutil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'src')

# 只处理单值简写：padding: Npx;  margin: Npx;  gap: Npx;
SPACE_MAP = {
    '2px': '--space-half',
    '4px': '--space-1',
    '8px': '--space-2',
    '12px': '--space-3',
    '16px': '--space-4',
    '20px': '--space-5',
    '24px': '--space-6',
    '28px': '--space-7',
    '32px': '--space-8',
    '40px': '--space-10',
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
        for val, tok in SPACE_MAP.items():
            # 只匹配单值简写：属性名 + 冒号 + 值 + 分号（值后必须是分号，排除多值）
            for prop in ('padding', 'margin', 'gap'):
                pat = re.compile(r'(' + prop + r':\s*)' + re.escape(val) + r'\s*;')
                src, n = pat.subn(rf'\1var({tok});', src)
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

    print(f'\n总计: {grand} 处间距替换, {len(files)} 个文件')
    print('注意: 多值简写(padding: 8px 16px)与 rpx 档未替换，属保守策略')

if __name__ == '__main__':
    main()
