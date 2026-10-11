#!/usr/bin/env python3
"""
AlphaReader 全量令牌化 - 批量替换脚本
用法：
  python3 tokenize.py --dry-run    # 预演，只输出将改动的内容，不写文件
  python3 tokenize.py --apply      # 实际执行替换
  python3 tokenize.py --apply --file pages/reports/index.vue   # 只处理单文件

原则：
  1. 只替换"安全映射"（App.vue 中已存在完全等价定义的色值），语义等价，渲染无变化
  2. 同值多令牌（如 #e8f0fe）不自动替换，输出到 --report 待人工决策
  3. 跳过 App.vue 自身（定义处）、node_modules、dist
  4. 保留原文件备份为 .bak，便于回滚
"""
import re, os, sys, argparse, shutil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'src')

# ── 安全映射：App.vue 中已存在完全等价定义，且语义唯一 ──
SAFE = {
    '#4285f4': '--color-brand',
    '#34c759': '--color-down',
    '#8c8c9a': '--color-text-muted',
    '#1a1a2e': '--color-text-primary',
    '#ff3b30': '--color-up',
    '#ff9500': '--color-warning',
    '#2563eb': '--color-info-hover',
    '#3b82f6': '--color-info',
    '#2e7d32': '--color-success-text',
    '#6b7280': '--color-neutral',
    '#3b78e7': '--color-brand-hover',
    '#007aff': '--color-brand-ios',
    '#1677ff': '--color-brand-alt',
    '#ef4444': '--color-up-alt',
    '#22c55e': '--color-down-alt',
    '#f59e0b': '--color-warning-alt',
    '#f5f5f7': '--color-bg-code',
    '#f5f7fa': '--color-bg-secondary',
    '#fafbfc': '--color-bg-hover',
    '#dcfce7': '--color-bg-success-light',
    '#e8f5e9': '--color-bg-success-soft',
    '#dbeafe': '--color-bg-info-light',
    '#eff6ff': '--color-bg-info-accent',
    '#f0f4ff': '--color-bg-info-blend',
    '#f3f4f6': '--color-bg-neutral-light',
    '#f5f5f5': '--color-bg-neutral-soft',
    '#f0f5ff': '--color-bg-brand-light',
    '#f0f0f5': '--color-bg-dropdown-hover',
    '#d0e0f8': '--color-bg-tag-hover',
    '#e8e8ed': '--color-border',
    '#f0f0f2': '--color-border-light',
    '#c0c0cc': '--color-border-hover',
    '#e0e0e6': '--color-border-divider',
    '#f2f2f5': '--color-border-subtle',
    '#d0d0d8': '--color-border-separator',
    '#3a3a4a': '--color-text-secondary',
    '#5a5a6e': '--color-text-tertiary',
    '#4a4a5a': '--color-text-body',
    '#b0b0be': '--color-text-placeholder',
    '#6b6b7b': '--color-text-hint',
    '#8e8e93': '--color-neutral-light',
    '#16a34a': '--color-success-dark',
    '#c62828': '--color-danger-dark',
    '#fff3e0': '--color-bg-warning-light',
    '#e65100': '--color-warning-deep',
    '#FF9800': '--color-time-morning',
    '#F44336': '--color-time-midday',
    '#9C27B0': '--color-time-evening',
    '#3F51B5': '--color-time-night',
    '#FFF3E0': '--color-bg-time-morning',
    '#F3E5F5': '--color-bg-time-evening',
    '#E8EAF6': '--color-bg-time-night',
    '#f8f8fa': '--color-bg-subtle',
    '#eb4b4b': '--color-danger',
    '#30b86e': '--color-success',
    '#43a047': '--color-success-hover',
    '#1e88e5': '--color-info-active',
    '#1565c0': '--color-info-deep',
    '#3b78dc': '--color-brand-deep',
    '#f5a623': '--color-warning-soft',
    '#eef4ff': '--color-bg-brand-softer',
    '#e3f2fd': '--color-bg-info-softer',
    '#f2f2f7': '--color-bg-subtle-alt',
    '#e5eaf1': '--color-bg-neutral-tint',
    '#c0c4cc': '--color-border-strong',
    '#f0f0f4': '--color-bg-active-press',
}

# 同值多令牌 / 需人工决策 —— 不自动替换，仅报告
AMBIGUOUS = {
    '#e8f0fe': ['--color-bg-tag', '--color-bg-info-soft'],
    '#f5f6f8': ['--color-bg-input', '--color-bg-active'],
}

# 圆角令牌化（px 档，供 PC 断点使用）
RADIUS_PX = {
    '3px': '--radius-xs', '4px': '--radius-xs',
    '5px': '--radius-sm', '6px': '--radius-sm',
    '8px': '--radius-md',
    '10px': '--radius-lg',
    '12px': '--radius-xl', '14px': '--radius-xl',
    '16px': '--radius-2xl',
    '20px': '--radius-3xl',
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
    ap.add_argument('--radius', action='store_true', help='同时执行圆角令牌化')
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        ap.error('必须指定 --dry-run 或 --apply')

    files = collect_files(args.file)
    grand = 0
    report_amb = []

    for p in files:
        src = open(p, encoding='utf-8').read()
        orig = src
        cnt = 0

        # 色值替换（大小写不敏感，保留原大小写风格）
        for hexv, tok in SAFE.items():
            pat = re.compile(re.escape(hexv), re.IGNORECASE)
            def rep(m):
                return f'var({tok})'
            src, n = pat.subn(rep, src)
            cnt += n
            # 同值多令牌检测
        for hexv, toks in AMBIGUOUS.items():
            pat = re.compile(re.escape(hexv), re.IGNORECASE)
            n = len(pat.findall(src))
            if n:
                report_amb.append((p, hexv, n, toks))

        # 圆角替换
        if args.radius:
            for val, tok in RADIUS_PX.items():
                pat = re.compile(r'border-radius:\s*' + re.escape(val) + r'\b')
                src, n = pat.subn(f'border-radius: var({tok})', src)
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

    print(f'\n总计: {grand} 处替换, {len(files)} 个文件')
    if report_amb:
        print('\n=== 需人工决策（同值多令牌，未自动替换）===')
        for p, hexv, n, toks in report_amb:
            print(f'{os.path.relpath(p, ROOT)}: {hexv} x{n} -> 候选 {toks}')

if __name__ == '__main__':
    main()
