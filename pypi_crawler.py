import requests
import json
import os
import time
import subprocess
from datetime import datetime, timedelta
from urllib.parse import urljoin
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GitHubActionsPyPICrawler:
    def __init__(self, download_dir="packages", max_packages=50, max_size_mb=100):
        self.download_dir = download_dir
        self.max_packages = max_packages  # 限制下载包数量
        self.max_size_mb = max_size_mb    # 单个文件最大大小限制(MB)
        self.max_total_size_mb = 500      # 总大小限制(MB)
        self.current_total_size = 0
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'PyPI-Crawler/1.0 (GitHub Actions)'
        })
        
        # 禁用代理，避免GitHub Actions环境中的代理问题
        self.session.proxies = {'http': None, 'https': None}
        
        # 创建下载目录
        os.makedirs(download_dir, exist_ok=True)
    
    def get_package_info(self, package_name):
        """获取包的详细信息"""
        url = f"https://pypi.org/pypi/{package_name}/json"
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"获取包 {package_name} 信息失败: {e}")
            return None
    
    def is_updated_since_july_2025(self, package_info):
        """检查包是否在2025年7月后更新"""
        try:
            # 获取最新版本的上传时间
            latest_version = package_info['info']['version']
            releases = package_info['releases']
            
            if latest_version in releases:
                release_files = releases[latest_version]
                if release_files:
                    # 获取最新文件的上传时间
                    upload_time = release_files[0]['upload_time_iso_8601']
                    upload_date = datetime.fromisoformat(upload_time.replace('Z', '+00:00'))
                    cutoff_date = datetime(2025, 7, 1, tzinfo=upload_date.tzinfo)
                    return upload_date >= cutoff_date
        except (KeyError, ValueError, IndexError) as e:
            logger.warning(f"解析时间失败: {e}")
        return False
    
    def get_file_size_mb(self, file_info):
        """获取文件大小(MB)"""
        size_bytes = file_info.get('size', 0)
        return size_bytes / (1024 * 1024)
    
    def download_package(self, package_name, package_info):
        """下载包的tar.gz文件"""
        try:
            latest_version = package_info['info']['version']
            releases = package_info['releases'][latest_version]
            
            # 寻找合适的文件（优先tar.gz，其次whl）
            suitable_file = None
            for file_info in releases:
                if file_info['filename'].endswith('.tar.gz'):
                    file_size_mb = self.get_file_size_mb(file_info)
                    if file_size_mb <= self.max_size_mb:
                        suitable_file = file_info
                        break
            
            if not suitable_file:
                # 如果没有合适的tar.gz，尝试找whl文件
                for file_info in releases:
                    if file_info['filename'].endswith('.whl'):
                        file_size_mb = self.get_file_size_mb(file_info)
                        if file_size_mb <= self.max_size_mb:
                            suitable_file = file_info
                            break
            
            if suitable_file:
                file_size_mb = self.get_file_size_mb(suitable_file)
                
                # 检查总大小限制
                if self.current_total_size + file_size_mb > self.max_total_size_mb:
                    logger.warning(f"总大小限制达到，跳过包: {package_name}")
                    return False
                
                download_url = suitable_file['url']
                filename = suitable_file['filename']
                file_path = os.path.join(self.download_dir, filename)
                
                # 检查文件是否已存在
                if os.path.exists(file_path):
                    logger.info(f"文件已存在，跳过: {filename}")
                    return True
                
                logger.info(f"下载: {filename} ({file_size_mb:.2f}MB)")
                response = self.session.get(download_url, timeout=60)
                response.raise_for_status()
                
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                
                self.current_total_size += file_size_mb
                logger.info(f"下载完成: {filename} (总大小: {self.current_total_size:.2f}MB)")
                
                # 创建包信息文件
                self.save_package_metadata(package_name, package_info, filename)
                
                return True
            else:
                logger.warning(f"未找到合适大小的文件: {package_name}")
                return False
                
        except Exception as e:
            logger.error(f"下载包 {package_name} 失败: {e}")
            return False
    
    def save_package_metadata(self, package_name, package_info, filename):
        """保存包的元数据信息"""
        metadata = {
            'name': package_name,
            'version': package_info['info']['version'],
            'summary': package_info['info']['summary'],
            'author': package_info['info']['author'],
            'license': package_info['info']['license'],
            'home_page': package_info['info']['home_page'],
            'download_filename': filename,
            'download_time': datetime.now().isoformat(),
            'package_url': f"https://pypi.org/project/{package_name}/"
        }
        
        metadata_path = os.path.join(self.download_dir, f"{package_name}_metadata.json")
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    def get_popular_packages_fallback(self):
        """备用方法：获取一些最近可能更新的包"""
        # 一些活跃的包名，可能在2025年7月后有更新
        popular_packages = [
            "requests", "urllib3", "certifi", "charset-normalizer",
            "pip", "setuptools", "wheel", "packaging",
            "numpy", "pandas", "matplotlib", "scipy",
            "flask", "django", "fastapi", "starlette",
            "boto3", "botocore", "aws-cdk-lib", "aws-cli",
            "tensorflow", "torch", "transformers", "openai",
            "pydantic", "sqlalchemy", "alembic", "click",
            "pytest", "black", "flake8", "mypy",
            "jupyter", "notebook", "ipython", "ipykernel"
        ]
        
        logger.info(f"使用备用包列表，共 {len(popular_packages)} 个包")
        return popular_packages
    
    def get_recent_packages_from_rss(self):
        """从PyPI的RSS源获取最近更新的包"""
        packages = []
        
        # 尝试多个RSS源
        rss_urls = [
            "https://pypi.org/rss/updates.xml",
            "https://pypi.org/rss/packages.xml"
        ]
        
        for rss_url in rss_urls:
            try:
                logger.info(f"尝试获取RSS: {rss_url}")
                response = self.session.get(rss_url, timeout=20)
                response.raise_for_status()
                
                # 简单的XML解析来获取包名
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                
                for item in root.findall('.//item'):
                    title = item.find('title')
                    if title is not None and title.text:
                        # 标题格式通常是 "package-name version"
                        package_name = title.text.split()[0]
                        if package_name and package_name not in packages:
                            packages.append(package_name)
                
                logger.info(f"从RSS获取到 {len(packages)} 个包")
                if packages:
                    return packages[:self.max_packages]
                    
            except Exception as e:
                logger.error(f"获取RSS {rss_url} 失败: {e}")
                continue
        
        # 如果RSS都失败了，使用备用方法
        logger.info("RSS获取失败，使用备用包列表...")
        return self.get_popular_packages_fallback()[:self.max_packages]
    
    def git_commit_and_push(self):
        """提交并推送到GitHub仓库"""
        try:
            # 配置git用户信息（在GitHub Actions中通常已配置）
            subprocess.run(['git', 'config', 'user.name', 'GitHub Actions'], check=True)
            subprocess.run(['git', 'config', 'user.email', 'actions@github.com'], check=True)
            
            # 添加所有新文件
            subprocess.run(['git', 'add', self.download_dir], check=True)
            
            # 检查是否有改动
            result = subprocess.run(['git', 'status', '--porcelain'], 
                                  capture_output=True, text=True, check=True)
            
            if result.stdout.strip():
                # 有改动，提交
                commit_message = f"Update PyPI packages - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                subprocess.run(['git', 'commit', '-m', commit_message], check=True)
                
                # 推送到远程仓库
                subprocess.run(['git', 'push'], check=True)
                logger.info("成功提交并推送到GitHub仓库")
            else:
                logger.info("没有新的改动需要提交")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Git操作失败: {e}")
        except Exception as e:
            logger.error(f"Git操作异常: {e}")
    
    def create_summary_report(self, downloaded_packages):
        """创建下载摘要报告"""
        report = {
            'download_time': datetime.now().isoformat(),
            'total_packages_downloaded': len(downloaded_packages),
            'total_size_mb': round(self.current_total_size, 2),
            'packages': downloaded_packages
        }
        
        report_path = os.path.join(self.download_dir, 'download_report.json')
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # 创建README
        readme_content = f"""# PyPI Packages Downloaded

## Download Summary
- **Download Time**: {report['download_time']}
- **Total Packages**: {report['total_packages_downloaded']}
- **Total Size**: {report['total_size_mb']} MB

## Packages List
"""
        for pkg in downloaded_packages:
            readme_content += f"- {pkg}\n"
        
        readme_path = os.path.join(self.download_dir, 'README.md')
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)
    
    def crawl_and_download(self, package_list=None):
        """主要的爬取和下载方法"""
        if package_list is None:
            # 获取最近更新的包列表
            package_list = self.get_recent_packages_from_rss()
        
        if not package_list:
            logger.error("未获取到包列表")
            return
        
        logger.info(f"开始处理 {len(package_list)} 个包")
        downloaded_packages = []
        downloaded_count = 0
        
        for i, package_name in enumerate(package_list, 1):
            # 检查是否达到下载限制
            if downloaded_count >= self.max_packages:
                logger.info(f"达到最大下载数量限制 ({self.max_packages})，停止下载")
                break
                
            logger.info(f"处理进度: {i}/{len(package_list)} - {package_name}")
            
            # 获取包信息
            package_info = self.get_package_info(package_name)
            if not package_info:
                continue
            
            # 检查是否在2025年7月后更新
            if not self.is_updated_since_july_2025(package_info):
                logger.info(f"包 {package_name} 不符合时间条件，跳过")
                continue
            
            # 下载包
            if self.download_package(package_name, package_info):
                downloaded_packages.append(package_name)
                downloaded_count += 1
            
            # 添加延迟，避免请求过于频繁
            time.sleep(0.5)
        
        logger.info(f"下载完成！共下载 {downloaded_count} 个包")
        
        # 创建摘要报告
        self.create_summary_report(downloaded_packages)
        
        # 提交到GitHub仓库
        self.git_commit_and_push()
        
        return downloaded_packages

# GitHub Actions环境检测
def is_github_actions():
    return os.environ.get('GITHUB_ACTIONS') == 'true'

# 使用示例
if __name__ == "__main__":
    # 针对GitHub Actions环境优化参数
    max_packages = int(os.environ.get('MAX_PACKAGES', '100'))  # 从环境变量获取，默认100
    max_size_mb = int(os.environ.get('MAX_SIZE_MB', '1'))    # 默认1MB
    
    if is_github_actions():
        logger.info("运行在GitHub Actions环境中")
    
    crawler = GitHubActionsPyPICrawler(
        download_dir="packages",
        max_packages=max_packages,
        max_size_mb=max_size_mb
    )
    
    # 测试网络连接
    logger.info("测试网络连接...")
    test_info = crawler.get_package_info("requests")
    if test_info:
        logger.info("网络连接正常！")
    else:
        logger.error("网络连接失败")
        exit(1)
    
    # 开始爬取
    downloaded = crawler.crawl_and_download()
    
    if downloaded:
        logger.info(f"成功下载包: {', '.join(downloaded)}")
    else:
        logger.warning("未下载任何包")
