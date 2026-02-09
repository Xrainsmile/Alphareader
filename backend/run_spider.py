import asyncio
import sys
import os

# 确保 Python 能找到 app 模块
sys.path.append('/app')

# 1. 导入你的工具 (根据你的截图路径)
from app.utils.redis import init_redis
from app.services.pipeline import run_pipeline

async def main():
    print("🔌 正在连接 Redis...")
    try:
        # 初始化 Redis 连接池
        await init_redis()
        print("✅ Redis 连接成功！")
        
        print("🚀 开始运行新闻抓取流水线...")
        # 运行流水线
        result = await run_pipeline()
        print(f"🎉 任务完成！结果: {result}")
        
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())