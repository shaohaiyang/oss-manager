# OSS 共享文件夹管理工具

基于阿里云 OSS Python SDK V2（`alibabacloud-oss-v2`）实现的命令行工具，用于管理共享目录：

```text
oss://your-bucket/shared
```

支持通过 `create`、`delete`、`modify`、`list` 对子文件夹和文件进行增删改查。

## 目录结构

```text
oss-manager/
├── oss_manager.py      # 主程序
├── requirements.txt    # Python 依赖
├── README.md           # 使用说明
└── .venv/              # 已安装依赖的虚拟环境
```

## 环境要求

- Python 3.8 及以上
- 阿里云 RAM 用户的 AccessKey，且该用户拥有 `your-bucket` Bucket 的读写权限

## 安装

项目目录下已创建好 `.venv`。如果需要在其他机器上重新安装：

```bash
cd oss-manager
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`oss_manager.py` 检测到当前 Python 缺少依赖时，会自动切换到项目内的 `.venv` 解释器运行。

## 配置

通过环境变量配置访问凭证和地域：

```bash
export OSS_ACCESS_KEY_ID='你的AccessKeyId'
export OSS_ACCESS_KEY_SECRET='你的AccessKeySecret'
export OSS_REGION='cn-hangzhou'   # 替换为 your-bucket 所在地域
```

可选环境变量：

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `OSS_REGION` | Bucket 所在地域 | 无，必填 |
| `OSS_ENDPOINT` | 自定义 Endpoint | 根据 Region 自动生成 |
| `OSS_ROOT` | 根目录 | `oss://your-bucket/shared` |
| `OSS_BUCKET` | Bucket 名称 | 从 `OSS_ROOT` 中解析，即 `your-bucket` |

也可以使用命令行参数覆盖：`--region`、`--endpoint`、`--root`、`--bucket`。

## 路径规则

命令中的路径默认相对于根目录 `oss://your-bucket/shared`，以下写法等价：

```bash
./oss_manager.py list docs
./oss_manager.py list shared/docs
./oss_manager.py list oss://your-bucket/shared/docs
```

路径不能包含 `..`。文件夹在 OSS 中通过以 `/` 结尾的对象标记，工具会自动处理。

## 命令总览

```text
oss_manager.py [全局参数] <命令> <对象类型> [参数]

全局参数:
  --region REGION     OSS 地域
  --endpoint ENDPOINT OSS Endpoint
  --root ROOT         根目录，默认 oss://your-bucket/shared
  --bucket BUCKET     Bucket 名称，覆盖 --root 中的 Bucket

命令:
  list                                                 列出文件夹和文件
  create folder <path>                                 创建文件夹
  create file <path>                                   创建文件
  delete folder <path>                                 删除文件夹
  delete file <path>                                   删除文件
  modify folder <path>                                 重命名/移动文件夹
  modify file <path>                                   修改内容/重命名/移动文件
```

查看帮助：

```bash
./oss_manager.py --help
./oss_manager.py create file --help
```

## 查询：list

```bash
# 列出根目录下的第一层内容
./oss_manager.py list

# 列出 docs 下的第一层内容
./oss_manager.py list docs

# 递归列出所有内容
./oss_manager.py list docs --recursive

# 显示类型、大小和最后修改时间
./oss_manager.py list docs --recursive --long
```

`--long` 输出示例：

```text
TYPE        SIZE  LAST MODIFIED        PATH
DIR            -  -                    docs/2026/
FILE         2 B  2026-11-06 10:00:00  docs/readme.txt
```

## 新增：create

### 创建文件夹

```bash
./oss_manager.py create folder docs/2026
```

### 创建文件

```bash
# 直接写入文本内容
./oss_manager.py create file docs/readme.txt --content 'hello'

# 从本地文件上传
./oss_manager.py create file docs/photo.jpg --from ./photo.jpg

# 从标准输入上传
echo 'hello' | ./oss_manager.py create file docs/readme.txt --from -

# 创建空文件
./oss_manager.py create file docs/empty.txt

# 文件已存在时覆盖
./oss_manager.py create file docs/readme.txt --content 'new' --overwrite
```

### create 参数

| 参数 | 说明 |
| --- | --- |
| `--content TEXT` | 文件内容为文本 |
| `--from LOCAL` | 从本地文件上传，`-` 表示标准输入 |
| `--overwrite` | 文件已存在时覆盖 |

`--content` 和 `--from` 不能同时使用。文件大于 5GB 时自动使用分片上传。

## 修改：modify

### 修改文件内容

```bash
./oss_manager.py modify file docs/readme.txt --content 'updated text'
./oss_manager.py modify file docs/photo.jpg --from ./new_photo.jpg
```

### 重命名文件（同一目录）

```bash
./oss_manager.py modify file docs/readme.txt --new-name notes.txt
```

### 移动文件

```bash
./oss_manager.py modify file docs/readme.txt --to archive/notes.txt
```

### 重命名文件夹（同一父目录）

```bash
./oss_manager.py modify folder docs/2026 --new-name archive
```

### 移动文件夹

```bash
./oss_manager.py modify folder docs/2026 --to archive/2026
```

### 修改文件内容并同时重命名

```bash
./oss_manager.py modify file docs/readme.txt --new-name notes.txt --content 'updated'
```

### modify 参数

| 参数 | 说明 |
| --- | --- |
| `--new-name NAME` | 在同一父目录下改名，不能包含 `/` |
| `--to PATH` | 移动到目标路径 |
| `--content TEXT` | 替换文件内容为文本（仅 modify file） |
| `--from LOCAL` | 从本地文件替换内容（仅 modify file） |
| `--overwrite` | 目标已存在时覆盖 |

`--new-name` 和 `--to` 不能同时使用。文件夹的重命名/移动本质是批量复制后删除旧对象；大于 5GB 的文件自动使用分片复制。

## 删除：delete

### 删除文件

```bash
./oss_manager.py delete file docs/notes.txt

# 文件不存在时不报错
./oss_manager.py delete file docs/notes.txt --force
```

### 删除空文件夹

```bash
./oss_manager.py delete folder docs/archive
```

### 递归删除非空文件夹

```bash
./oss_manager.py delete folder docs/archive --recursive
```

### delete 参数

| 参数 | 说明 |
| --- | --- |
| `--recursive` | 删除文件夹下所有对象（仅 delete folder） |
| `--force` | 目标不存在时不报错 |

> 警告：`delete folder --recursive` 会删除该前缀下所有文件和子文件夹，且不可恢复，请确认路径后再执行。

## 完整示例

```bash
export OSS_ACCESS_KEY_ID='...'
export OSS_ACCESS_KEY_SECRET='...'
export OSS_REGION='cn-hangzhou'

cd oss-manager

# 创建目录与文件
./oss_manager.py create folder docs
./oss_manager.py create file docs/readme.txt --content 'hello'
./oss_manager.py create folder docs/2026
./oss_manager.py create file docs/2026/plan.md --from ./plan.md

# 查询
./oss_manager.py list docs --recursive --long

# 重命名文件、移动文件夹
./oss_manager.py modify file docs/readme.txt --new-name notes.txt
./oss_manager.py modify folder docs/2026 --to archive/2026

# 删除
./oss_manager.py delete file docs/notes.txt
./oss_manager.py delete folder archive --recursive
```

## 使用 rclone

除 `oss_manager.py` 外，也可以直接用 rclone 管理同一目录。rclone 通过 S3 兼容接口访问阿里云 OSS，对应关系如下：

| 项目 | 值 |
| --- | --- |
| remote 名称 | `aliyun` |
| Bucket | `your-bucket` |
| 根前缀 | `shared/` |
| rclone 路径 | `aliyun:your-bucket/shared/` |

### 配置文件

配置文件位置：

```bash
~/.config/rclone/rclone.conf
```

在其他机器上按以下方式创建：

```bash
export OSS_ACCESS_KEY_ID='...'
export OSS_ACCESS_KEY_SECRET='...'
export OSS_REGION='cn-hangzhou'

rclone config create aliyun s3 \
  provider=Alibaba \
  access_key_id="$OSS_ACCESS_KEY_ID" \
  secret_access_key="$OSS_ACCESS_KEY_SECRET" \
  endpoint=oss-cn-hangzhou.aliyuncs.com \
  region=cn-hangzhou \
  no_check_bucket=true

chmod 600 ~/.config/rclone/rclone.conf
```

`no_check_bucket=true` 用于避免 rclone 在 `mkdir` 等操作前反复检查或尝试创建已存在的 Bucket，否则可能报 `BucketAlreadyExists`。

> rclone 对 S3 的 `secret_access_key` 是明文保存在配置文件中的，请勿提交到 Git，并确保配置文件权限为 `600`。

### 验证配置

```bash
rclone listremotes
rclone lsd aliyun:
rclone lsf aliyun:your-bucket/shared/
```

### 查看

```bash
# 列出根目录第一层
rclone lsf aliyun:your-bucket/shared/

# 只列目录
rclone lsf aliyun:your-bucket/shared/ --dirs-only

# 递归列出
rclone lsf -R aliyun:your-bucket/shared/

# 查看文件大小和修改时间
rclone lsl aliyun:your-bucket/shared/

# 查看某个子目录
rclone lsf aliyun:your-bucket/shared/docs/
```

### 上传与下载

```bash
# 上传单个文件
rclone copy ./readme.txt aliyun:your-bucket/shared/docs/

# 上传整个目录
rclone copy ./docs aliyun:your-bucket/shared/docs

# 下载单个文件
rclone copy aliyun:your-bucket/shared/docs/readme.txt ./downloads/

# 下载整个目录
rclone copy aliyun:your-bucket/shared/docs ./downloads/docs
```

`copy` 只新增或覆盖，不删除目标端多余文件；需要让目标端与本地完全一致时使用 `sync`：

```bash
# 先预览将要执行的操作
rclone sync ./docs aliyun:your-bucket/shared/docs --dry-run

# 确认后执行
rclone sync ./docs aliyun:your-bucket/shared/docs
```

> `sync` 会删除目标端在本地不存在的文件，执行前务必确认路径或先加 `--dry-run`。

### 移动、重命名与删除

```bash
# 重命名/移动文件
rclone moveto aliyun:your-bucket/shared/docs/readme.txt aliyun:your-bucket/shared/docs/notes.txt

# 移动目录
rclone move aliyun:your-bucket/shared/docs/2026 aliyun:your-bucket/shared/archive/2026

# 删除单个文件
rclone deletefile aliyun:your-bucket/shared/docs/notes.txt

# 删除目录下所有文件（保留目录本身）
rclone delete aliyun:your-bucket/shared/docs/

# 递归删除目录及其内容
rclone purge aliyun:your-bucket/shared/archive
```

> `purge` 会删除整个前缀且不可恢复，执行前务必确认路径。

### 创建目录

OSS/S3 没有真正的空目录，因此 **rclone 无法创建空文件夹**，执行 `rclone mkdir` 只会输出警告并退出：

```text
Warning: running mkdir on a remote which can't have empty directories does nothing
```

需要创建空文件夹时，使用本项目提供的 `oss_manager.py`（会在 OSS 中写入 `docs/` 目录标记）：

```bash
./oss_manager.py create folder docs
```

也可以直接向目标前缀上传一个文件，前缀会随之出现：

```bash
rclone copy ./readme.txt aliyun:your-bucket/shared/docs/
```

如果 `rclone mkdir` 报 `BucketAlreadyExists`，在 remote 配置中添加 `no_check_bucket = true`，或临时使用：

```bash
rclone mkdir aliyun:your-bucket/shared/docs --s3-no-check-bucket
```

### 挂载为本地目录

```bash
mkdir -p ~/oss-shared
rclone mount aliyun:your-bucket/shared ~/oss-shared --vfs-cache-mode writes
```

后台运行，并开启 RC 接口以便手动刷新缓存：

```bash
rclone mount aliyun:your-bucket/shared ~/oss-shared \
  --vfs-cache-mode writes --daemon \
  --rc --rc-addr 127.0.0.1:5572 --rc-no-auth
```

卸载：

```bash
fusermount -u ~/oss-shared
```

### 缓存与刷新

rclone 不是实时同步的，目录列表有多层缓存：

| 缓存 | 参数 | 默认值 | 作用 |
| --- | --- | --- | --- |
| 目录缓存 | `--dir-cache-time` | `5m` | 目录列表缓存时长 |
| VFS 缓存轮询 | `--vfs-cache-poll-interval` | `1m` | 挂载时检查缓存过期的间隔 |
| 远端轮询 | `--poll-interval` | `1m` | 仅对支持推送变更的 remote 有效（OSS/S3 不支持） |

- 本进程自己的写操作会立即让相关缓存失效。
- 其他客户端/进程产生的变更，需等 `--dir-cache-time` 过期后才会出现。
- 想接近实时，可调小间隔：

```bash
rclone mount aliyun:your-bucket/shared ~/oss-shared \
  --vfs-cache-mode writes --daemon \
  --rc --rc-addr 127.0.0.1:5572 --rc-no-auth \
  --dir-cache-time 10s --vfs-cache-poll-interval 10s
```

- 挂载时带了 `--rc`，可不重启进程手动强制刷新：

```bash
rclone rc vfs/refresh recursive=true --rc-addr 127.0.0.1:5572
```

> `--rc` 只有 `rclone mount` 支持，`copy/sync/ls` 等命令无法通过它刷新。
> 客户端与服务端地址要一致：服务端绑 `127.0.0.1` 时，客户端也要写 `--rc-addr 127.0.0.1:5572`，否则默认的 `localhost` 可能被解析成 IPv6 `::1` 而连接失败。

### 过滤与校验

```bash
# 只复制 .md 文件
rclone copy ./docs aliyun:your-bucket/shared/docs --include '*.md'

# 排除临时文件
rclone sync ./docs aliyun:your-bucket/shared/docs --exclude '*.tmp'

# 校验两端差异
rclone check ./docs aliyun:your-bucket/shared/docs
```

### oss_manager.py 与 rclone 的取舍

| 场景 | 推荐 |
| --- | --- |
| 精确创建空文件夹、重命名文件夹、修改文件内容 | `oss_manager.py` |
| 批量上传/下载、目录同步、挂载、过滤 | `rclone` |

两者操作的是同一批 OSS 对象，可以混合使用。

## 注意事项

1. **必须先配置 `OSS_REGION`**。Bucket `your-bucket` 所在的地域需要填写正确，否则会出现域名或签名错误。
2. **OSS 没有真实目录**。文件夹是 key 以 `/` 结尾的空对象；没有显式文件夹标记的前缀也会被视为目录。
3. **删除非空文件夹必须加 `--recursive`**，避免误删。
4. **文件夹改名/移动不是原子操作**。工具会先复制所有对象到新前缀，再删除旧前缀；对象较多时耗时较长，中途失败可能留下部分副本。
5. **同名目标默认不覆盖**。修改或创建时如需覆盖，请显式添加 `--overwrite`。
6. **大文件支持**。单次上传/复制超过 5GB 时自动使用分片方式；普通文件仍为单次请求。

## 常见问题

### `ModuleNotFoundError: No module named 'alibabacloud_oss_v2'`

项目 `.venv` 缺失或依赖未安装：

```bash
cd oss-manager
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

正常情况下直接运行 `./oss_manager.py` 会自动使用 `.venv`。

### `region is required`

未设置地域：

```bash
export OSS_REGION='cn-hangzhou'
```

或使用参数：

```bash
./oss_manager.py --region cn-hangzhou list
```

### `AccessDenied` / `403`

检查 AccessKey 是否正确、RAM 用户是否拥有 `your-bucket` Bucket 的读写权限。

### `NoSuchBucket` 或域名解析错误

检查 `OSS_REGION` 是否与 Bucket 实际所在地域一致，`--root` 中的 Bucket 名称是否为 `your-bucket`。

### `rclone rc vfs/refresh` 报 `connection refused`

```
dial tcp [::1]:5572: connect: connection refused
```

原因通常有两个：

1. 挂载时没有加 `--rc`，或进程已退出、端口没有监听。检查：

   ```bash
   ps -ef | grep "[r]clone"
   ss -ltnp | grep 5572
   ```

2. 客户端连的是 `localhost`（可能解析为 IPv6 `::1`），而服务端绑的是 IPv4。调用时显式指定地址：

   ```bash
   rclone rc vfs/refresh recursive=true --rc-addr 127.0.0.1:5572
   ```

### `authentication must be set up on the rc server ...`

```
authentication must be set up on the rc server to use "vfs/refresh"
or the --rc-no-auth flag must be in use
```

`--rc-no-auth` 是**服务端（mount）**参数，不能加在 `rclone rc` 客户端上。二选一：

```bash
# 方式一：挂载端允许无认证（仅限本机）
rclone mount ... --rc --rc-addr 127.0.0.1:5572 --rc-no-auth

# 方式二：设置账号密码，客户端调用时带上相同凭证
rclone mount ... --rc --rc-addr 127.0.0.1:5572 --rc-user admin --rc-pass '密码'
rclone rc vfs/refresh recursive=true --rc-addr 127.0.0.1:5572 \
  --rc-user admin --rc-pass '密码'
```

### 挂载点报 `Transport endpoint is not connected`

rclone 进程已退出，但 FUSE 挂载点残留。惰性卸载后重新挂载：

```bash
fusermount -uz ~/oss-shared
rclone mount aliyun:your-bucket/shared ~/oss-shared \
  --vfs-cache-mode writes --daemon \
  --rc --rc-addr 127.0.0.1:5572 --rc-no-auth
```

如仍无法卸载，使用 `sudo umount -l ~/oss-shared`。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| `0` | 成功 |
| `1` | OSS 服务或 SDK 错误 |
| `2` | 参数或路径校验错误 |
| `130` | 用户中断（Ctrl+C） |
