# W2M — Where to meet

Ứng dụng tìm điểm gặp cho 4 người trên mạng đường có hướng tại Hà Nội.

**Hiện trạng:** M0 hoàn thành ở môi trường local. Người phát triển xác nhận frontend install,
audit (0 vulnerabilities), lint, typecheck và production build đạt với Next.js 16.4.5.
Backend đã qua Ruff và 26 test với Python 3.12.13; có một cảnh báo deprecation
TestClient/httpx. Người phát triển đã xác nhận Uvicorn khởi động và smoke test HTTP
backend đạt: health 200, ready/map config 503 đúng kỳ vọng; trang chủ frontend đã
hiển thị. Git và hai lockfile đã có; remote CI chưa được xác minh. Chưa có dữ liệu
OSM, bản đồ tương tác hoặc thuật toán tìm điểm gặp.

- [Đặc tả v0.2.0](docs/spec/W2M%20—%20Software%20%26%20Technical%20Specification%20v0.2.0.md)
- [Kế hoạch MVP và checklist](docs/plans/W2M-MVP-Plan.md)
- [Bổ sung hợp đồng M0](docs/spec/W2M-M0-Contract-Addendum.md)

## Yêu cầu

- Python 3.12 (có thể cài bằng uv), uv và Node.js 22/npm.
- Chạy lệnh backend từ thư mục gốc để `.env` và đường dẫn dữ liệu được đọc đúng.
- Các lệnh dưới đây dành cho người phát triển tự chạy; chưa được chạy trong phiên viết M0.

## 1. Chuẩn bị và khóa dependency

Từ thư mục gốc dự án:

```sh
git init
cp .env.example .env
cp frontend/.env.example frontend/.env.local
uv python install 3.12
uv lock --project backend
uv sync --project backend --locked
npm --prefix frontend install
```

Nếu đã có Git hoặc file môi trường, bỏ qua bước tương ứng; giữ cấu hình đã chỉnh.
Hai lệnh quản lý dependency sinh `backend/uv.lock` và `frontend/package-lock.json`.
Commit cả hai file này. Manifest chỉ giới hạn phiên bản tương thích; **dependency
chưa được khóa hoàn chỉnh cho đến khi sinh và kiểm tra hai lockfile**.
CI cố ý dùng `--locked` và `npm ci`, không tự chọn lại dependency trên từng lần chạy.

Nhóm offline `osmnx/geopandas` thuộc M1; khi cần cài bằng:

```sh
uv sync --project backend --locked --extra data
```

## 2. Chạy kiểm tra M0

Từ thư mục gốc:

```sh
uv run --project backend --locked ruff check backend
uv run --project backend --locked pytest backend/tests
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Nếu có lỗi, gửi nguyên output để sửa; không đánh dấu cổng nghiệm thu khi chưa chạy.
Backend test chỉ dùng fixture tổng hợp, không truy cập OSM hay dịch vụ ETA.
Frontend M0 được kiểm tra bằng lint, typecheck và build; chưa có bài E2E.

## 3. Chạy development

Terminal 1, tại thư mục gốc:

```sh
uv run --project backend --locked uvicorn app.main:app --app-dir backend --reload --port 8000
```

Terminal 2, tại thư mục gốc:

```sh
npm --prefix frontend run dev
```

Mở frontend tại `http://localhost:3000`, OpenAPI tại `http://localhost:8000/docs`.
Frontend M0 là trang khởi tạo; chưa gọi API hoặc hiển thị bản đồ.

Kiểm tra thủ công tại terminal khác:

```sh
curl -i http://localhost:8000/health
curl -i http://localhost:8000/ready
curl -i http://localhost:8000/api/v1/map/config
```

Kỳ vọng: health 200; ready và map config 503 `GRAPH_UNAVAILABLE`.
503 là đúng ở M0: graph loader chưa triển khai. Không sửa readiness thành 200 chỉ
để qua smoke test. API meeting/rerank cũng chưa chạy thuật toán.

## Cấu trúc và cấu hình

- `backend/app`: FastAPI, cấu hình, request/response models và endpoint chờ tích hợp.
- `backend/tests`: kiểm tra validation, health/readiness và fixture graph.
- `backend/data`: AOI/graph sẽ được chuẩn bị ở M1; không commit artifact lớn.
- `frontend`: Next.js App Router, TypeScript contracts và trang khởi tạo.
- `.github/workflows/ci.yml`: backend lint/test và frontend lint/typecheck/build.

Backend đọc `.env` gốc, prefix `W2M_`; xem chú thích trong `.env.example`.
Frontend đọc `frontend/.env.local`; mọi biến `NEXT_PUBLIC_*` đều công khai cho browser.
Không đưa secret vào những biến này. M0 chưa cần tile URL; chọn nguồn tile và
rà soát attribution/điều khoản khi triển khai bản đồ ở M5.

Không log request body hoặc tọa độ chính xác. Lỗi validation trả thông báo tổng quát
và request ID. Cache, AOI validation và thuật toán thuộc M1–M4; Docker thuộc M6.

## Kết quả M0 và theo dõi

### Cập nhật bảo mật dependency frontend

Manifest yêu cầu MapLibre `^6.4.1` trở lên để tránh
[GHSA-jrc7-96c5-q579](https://github.com/advisories/GHSA-jrc7-96c5-q579).
Trong M0 chưa có code tích hợp MapLibre nên chưa có API bản đồ phải chuyển đổi.

`@typescript-eslint/typescript-estree` được override riêng sang minimatch
`^11.0.1` để tránh [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249).
Không override mọi bản minimatch của các package khác. Đây là override vượt major
mà parser đang khai báo; minimatch 11 có thay đổi API, nên cần kiểm tra lint thực tế.
Gỡ override khi parser phát hành dependency đã vá chính thức.

ESLint 9 vẫn giữ để tương thích bộ plugin hiện có; cảnh báo hết hỗ trợ chưa được
xử lý trong lần sửa audit này. Không coi việc hết hỗ trợ là đã giải quyết chỉ vì
audit không còn phát hiện lỗ hổng.

Người phát triển chạy từ thư mục gốc:

```sh
npm --prefix frontend install
npm --prefix frontend audit
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

`npm install` sẽ cập nhật lockfile hiện tại; không xóa lockfile hoặc dùng
`audit fix --force`. Commit `frontend/package.json` và lockfile sau khi kiểm tra.
Người phát triển đã cung cấp output xác nhận toàn bộ các lệnh trên chạy thành công:
audit báo 0 vulnerabilities; lint/typecheck/build đạt. Đây là kết quả local do người
phát triển chạy, chưa phải kết quả CI hoặc kiểm chứng runtime bản đồ.

### Trạng thái nghiệm thu

- Git và hai lockfile đã tồn tại; backend đã chạy thành công với `--locked`. Chưa thực hiện commit hoặc xác minh remote CI trong task này.
- Ruff và 26 pytest backend đã đạt; frontend lint/typecheck/build đã đạt. Cảnh báo deprecation TestClient/httpx còn cần theo dõi.
- Backend đã khởi động và qua smoke test health/readiness/map config; người phát triển xác nhận trang chủ frontend tại `http://localhost:3000` đã hiển thị. M0 hoàn thành local.
- Cập nhật checklist theo bằng chứng thực tế. Không tạo journal chỉ để ghi kết quả kiểm tra hoặc cập nhật tài liệu, theo AGENTS.md.
