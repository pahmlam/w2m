# W2M — Where to meet

Ứng dụng tìm điểm gặp cho 4 người trên mạng đường có hướng tại Hà Nội, dựa trên
thời gian di chuyển và mức ưu tiên công bằng của cả nhóm.

Backend đã hỗ trợ định tuyến CSR, tìm điểm gặp và rerank trên bundle Vành đai 3.
Frontend hiển thị bản đồ và phạm vi hỗ trợ từ backend. Xem tiến độ triển khai
tại [kế hoạch MVP](docs/plans/W2M-MVP-Plan.md).

## Chạy local bằng Docker Compose

Cần Docker có Compose v2 và thư mục `validated` của bundle Vành đai 3
`hanoi-ring3-car-v1-3000-v1`. Compose dùng bundle trong
`backend/data/builds/hanoi-ring3-car-v1-3000-v1/validated` mặc định. Nếu bundle
nằm ở nơi khác, đặt `W2M_GRAPH_BUNDLE` thành đường dẫn tới thư mục đó. Chuẩn bị
bundle theo [pipeline offline](#pipeline-dữ-liệu-offline--m1) trước khi chạy.

```sh
docker compose up --build --detach --wait
curl --fail http://localhost:8000/ready
docker compose ps
```

Mở `http://localhost:3000`, đặt bốn vị trí trong AOI và bấm **Find a spot**.
Chọn một điểm gặp để xem bốn tuyến A–D. Hai cổng chỉ mở trên máy local.
Nếu cổng đã được dùng, chạy lệnh khởi động với
`W2M_FRONTEND_PORT=3001 W2M_BACKEND_PORT=8001` ở trước lệnh và dùng các cổng
tương ứng trong trình duyệt. Compose ghép URL API và CORS từ hai cổng này.

Backend kiểm tra metadata và checksum khi nạp bundle được mount chỉ đọc.
Frontend khởi động sau khi `/ready` trả 200. Nếu quá trình chờ lỗi, chạy
`docker compose logs backend` để kiểm tra bundle và quyền đọc. Dùng
`docker compose down` để dừng hai dịch vụ.

Bản đồ nền mặc định dùng OpenFreeMap Positron. Để đổi nguồn tile cho Docker,
đặt các biến `NEXT_PUBLIC_MAP_*` trong môi trường shell hoặc `.env` ở thư mục gốc,
rồi chạy lại `docker compose up --build --detach --wait`. Với tile raster, đặt
`NEXT_PUBLIC_MAP_STYLE_URL=` và điền URL tile cùng ghi công nhà cung cấp theo
[tài liệu nguồn tile](docs/plans/W2M-M6-Tile-Provider.md).

## Yêu cầu và cài đặt

Cần Python 3.12, uv và Node.js 22/npm. Chạy các lệnh dưới đây từ thư mục gốc repo
để `.env` và đường dẫn dữ liệu được đọc đúng.

Chỉ sao chép file môi trường khi chưa có; giữ nguyên cấu hình đang sử dụng:

```sh
cp .env.example .env
cp frontend/.env.example frontend/.env.local
```

Cài dependency từ hai lockfile đã có trong repo:

```sh
uv python install 3.12
uv sync --project backend --locked --extra data
npm --prefix frontend ci
```

Extra `data` cung cấp OSMnx/GeoPandas cho các CLI offline và test roundtrip GraphML.
Nếu chỉ chạy API nền tảng, có thể bỏ `--extra data`; khi không có OSMnx, các test
roundtrip tương ứng sẽ bị bỏ qua. Không cần sinh lại lockfile khi cài đặt thông thường.

## Chạy development

Terminal 1:

```sh
W2M_GRAPH_DIR=backend/data/builds/hanoi-ring3-car-v1-3000-v1/validated \
  uv run --project backend --locked uvicorn app.main:app --app-dir backend --reload --port 8000
```

Terminal 2:

```sh
npm --prefix frontend run dev
```

- Frontend: `http://localhost:3000`.
- Swagger/OpenAPI: `http://localhost:8000/docs`.

Trang chính tải AOI từ `GET /api/v1/map/config` và căn bản đồ theo phạm vi này.
Nếu graph chưa sẵn sàng, bấm **Try again** sau khi `GET /ready` trả 200.
Đặt đủ bốn vị trí A–D rồi bấm **Find a spot** để xem danh sách theo thứ hạng từ backend.

### Bản đồ nền local

Mẫu cấu hình dùng raster **CARTO Positron**. Điền URL tile và ghi công nhà cung
cấp trong `frontend/.env.local` theo `frontend/.env.example`. Nếu có
`NEXT_PUBLIC_MAP_STYLE_URL`, ứng dụng ưu tiên style MapLibre JSON đó. Khởi động
lại dev server hoặc build lại bản production sau khi đổi biến môi trường.

Bản đồ luôn ghi công OpenStreetMap. Khi thiếu cấu hình tile, ứng dụng thông báo
và hiển thị các lớp AOI, vị trí và tuyến trên nền trống. Xem nguồn tile, yêu cầu
API key, giấy phép và xử lý sự cố trong [tài liệu vận hành M6](docs/plans/W2M-M6-Tile-Provider.md).

### API local

| Endpoint | Hành vi hiện tại |
|---|---|
| `GET /health` | 200 khi process chạy |
| `GET /ready` | 200 khi nạp được CSR, 503 `GRAPH_UNAVAILABLE` nếu bundle thiếu hoặc không hợp lệ |
| `GET /api/v1/map/config` | Trả AOI GeoJSON, phiên bản bundle và tham số runtime |
| `POST /api/v1/meeting-points` | Tính điểm gặp và tuyến bằng CSR |
| `POST /api/v1/meeting-points/{request_id}/rerank` | Xếp hạng từ bảng đã cache, trả 409 `RECOMPUTE_REQUIRED` nếu cần tính lại |

Đặt `W2M_GRAPH_DIR` trong `.env` trỏ đến thư mục đầu ra `validated` của bundle
đồ thị offline. Backend nạp CSR ở startup. `W2M_CSR_MAX_CONCURRENT_TASKS` giới hạn
số tác vụ tính toán CSR chạy cùng lúc trên mỗi process backend, mặc định là 2.
Service CSR đo từng bước theo mili giây. `scan` gồm lọc và tính điểm OWA.
`rank` gồm sắp xếp và chọn điểm theo khoảng cách. `total` đo từ khi tác vụ
bắt đầu chạy đến khi dựng xong kết quả, bao gồm cả bước tạo overlay.
Các endpoint nghiệp vụ trả 503 `GRAPH_UNAVAILABLE` khi chưa nạp được đồ thị. Lỗi validation trả 400
`INVALID_COORDINATES` hoặc `INVALID_PARAMETERS`.

Có thể kiểm tra HTTP bằng:

```sh
curl -i http://localhost:8000/health
curl -i http://localhost:8000/ready
curl -i http://localhost:8000/api/v1/map/config
```

## Kiểm thử

```sh
uv run --project backend --locked --extra data ruff check backend
uv run --project backend --locked --extra data pytest backend/tests
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
node --test frontend/tests/*.test.mjs
```

Test backend dùng fixture cố định và OSMnx giả lập cho bước tải; không gọi OSM hoặc
ETA service. Các test roundtrip dùng OSMnx thật để lưu/nạp graph tổng hợp local.
CI tại `.github/workflows/ci.yml` chạy backend Ruff/pytest và frontend
lint/typecheck/build; hiện chưa cài extra `data`, nên không kiểm tra toàn bộ roundtrip.

### E2E M5 với bundle Vành đai 3

Khởi động backend và frontend bằng Compose hoặc theo mục **Chạy development**,
rồi chạy các lệnh sau. Nếu dùng cổng frontend khác, đặt
`W2M_E2E_FRONTEND_URL` thành URL frontend thực tế.
Chromium chỉ cần cài một lần. Bộ E2E dùng graph thật, chặn tile ngoài và mô phỏng
lỗi mạng cùng phản hồi đến muộn.

```sh
npm --prefix frontend exec -- playwright install chromium --only-shell
npm --prefix frontend run test:e2e
```

Bằng chứng local trước M5:

- Backend: Ruff và **276 test đạt**, không bỏ qua, sau bước xuất CSR
  ngày 2026-11-11. Còn 58 cảnh báo deprecation Shapely/TestClient.
- Frontend: người phát triển đã xác nhận install/audit (0 vulnerabilities),
  lint/typecheck/build và trang chủ hoạt động ở M0; chưa chạy lại trong các task M1.
- Remote CI và benchmark MVP chưa được xác minh.

## Pipeline dữ liệu offline — M1

```text
Polygon AOI nguồn
  → prepare_aoi           → AOI và routing area có buffer
  → download_osm         → snapshot GraphML thô
  → prepare_graph_geometry → geometry EPSG:32648, chiều dài mét
  → prepare_graph_weights  → tốc độ và thời gian cạnh car-v1
  → prepare_graph_scc       → SCC lớn nhất, GeoJSON phần bị loại
  → prepare_reverse_edges   → ánh xạ cặp cạnh ngược và báo cáo
  → prepare_graph_split     → cạnh ≤ 60 giây, cắt biên AOI, lineage và mapping mới
  → prepare_graph_candidates → cờ phạm vi AOI và điều kiện làm điểm gặp
  → prepare_graph_csr        → CSR, ánh xạ node/cung và geometry có phiên bản
  → validate_graph           → báo cáo validation và metadata đầy đủ
```

Mỗi CLI chạy riêng; các bước truyền dữ liệu qua file, không tự gọi bước kế tiếp.
Chỉ `download_osm` tải OSM qua mạng. API và startup không gọi các CLI này.

### Artifact local đã kiểm tra

| Bước | Thư mục trong `backend/data/` | Kết quả |
|---|---|---|
| Snapshot | `osm/drive-20261106T092834Z/` | 21.129 node, 36.912 cạnh |
| Hình học | `geometry/drive-20261106T092834Z-utm-v1/` | Giữ topology, geometry theo chiều cạnh, chiều dài mét |
| Trọng số | `weighted/drive-20261106T092834Z-car-v1/` | 40 cạnh dùng default, 44 cạnh bị maxspeed giới hạn |
| SCC | `scc/drive-20261106T092834Z-car-v1-scc-v2/` | Giữ 20.162 node, 35.466 cạnh; loại 967 node, 1.446 cạnh |
| Cạnh ngược | `reverse-edges/drive-20261106T092834Z-car-v1-reverse-v1/` | 13.803 cặp; 7.860 cạnh one-way không ghép; không mơ hồ |
| Chia cạnh | `split/drive-20261106T092834Z-car-v1-split-v1/` | 20.221 node, 35.556 cạnh; max 56,178 giây |
| Gắn cờ ứng viên | `candidates/drive-20261106T092834Z-car-v1-candidates-v1/` | 2.504 ứng viên, gồm 50 node trên biên AOI |
| CSR | `csr/hanoi-pilot-car-v1-csr-v1/` | 20.221 node, 35.556 cung; đối chiếu NetworkX từ 20 nguồn đạt |

Artifact lớn được Git ignore; chúng không có sẵn chỉ nhờ clone repo. Nếu đã có
snapshot local ở trên thì tái sử dụng, không cần tải OSM lại. Snapshot có cutoff
`2026-11-06T09:28:34Z`; các bước sau lưu checksum và metadata để truy vết.

AOI `hanoi-pilot-v1` là hình chữ nhật WGS84 `[105.84, 21.02, 105.86, 21.04]`,
khoảng 4,60 km²; routing area sau buffer 3.000 m khoảng 58,62 km². Đây là vùng
kỹ thuật thử nghiệm, chưa phải AOI toàn nội đô Vành đai 3 đã được rà soát.

### Chạy các bước

Tạo AOI/routing area từ polygon nguồn trong config:

```sh
PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_aoi
```

Bước này xuất `aoi.geojson`, `routing_area.geojson`, `aoi.metadata.json`; ghi đè
các file đầu ra cùng đường dẫn nếu đã tồn tại. Điểm trên biên AOI được chấp nhận.

Khi cần snapshot mới, chạy riêng:

```sh
PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.download_osm
```

Lệnh in thư mục snapshot mới theo thời điểm UTC. Với snapshot hiện có, chạy các
bước còn lại như dưới đây; nếu vừa tải mới thì thay đường dẫn đầu vào tương ứng:

```sh
PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_graph_geometry \
  --snapshot-dir backend/data/osm/drive-20261106T092834Z \
  --output-dir backend/data/geometry/drive-20261106T092834Z-utm-v1

PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_graph_weights \
  --geometry-dir backend/data/geometry/drive-20261106T092834Z-utm-v1 \
  --profile backend/app/config/speed_profiles/car-v1.yaml \
  --output-dir backend/data/weighted/drive-20261106T092834Z-car-v1

PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_graph_scc \
  --weighted-dir backend/data/weighted/drive-20261106T092834Z-car-v1 \
  --aoi backend/data/aoi.geojson \
  --output-dir backend/data/scc/drive-20261106T092834Z-car-v1-scc-v2

PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_reverse_edges \
  --scc-dir backend/data/scc/drive-20261106T092834Z-car-v1-scc-v2 \
  --output-dir backend/data/reverse-edges/drive-20261106T092834Z-car-v1-reverse-v1

PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_graph_split \
  --scc-dir backend/data/scc/drive-20261106T092834Z-car-v1-scc-v2 \
  --reverse-dir backend/data/reverse-edges/drive-20261106T092834Z-car-v1-reverse-v1 \
  --output-dir backend/data/split/drive-20261106T092834Z-car-v1-split-v1

PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_graph_candidates \
  --split-dir backend/data/split/drive-20261106T092834Z-car-v1-split-v1 \
  --output-dir backend/data/candidates/drive-20261106T092834Z-car-v1-candidates-v1

PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_graph_csr \
  --candidates-dir backend/data/candidates/drive-20261106T092834Z-car-v1-candidates-v1 \
  --output-dir backend/data/csr/hanoi-pilot-car-v1-csr-v1 \
  --graph-version hanoi-pilot-car-v1-csr-v1

PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.validate_graph \
  --csr-dir backend/data/csr/hanoi-pilot-car-v1-csr-v1 \
  --aoi-metadata backend/data/aoi.metadata.json \
  --output-dir backend/data/validated/hanoi-pilot-car-v1-csr-v1
```

## Kiểm tra prototype tham chiếu M2

Chạy bộ kiểm thử offline và xuất báo cáo trên bundle đã validation của M1:

```bash
uv run --project backend --locked --extra data pytest backend/tests \
  --junitxml=backend/data/reports/m2-tests.xml

PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.validate_reference \
  --bundle-dir backend/data/builds/hanoi-ring3-car-v1-3000-v1/validated \
  --output backend/data/reports/m2-reference.json \
  --seed 20261115
```

CLI sinh bốn nguồn tổng hợp từ đường trong AOI, chạy NetworkX với cutoff 3.600
giây rồi xuất kết quả tại phi 0/0,5/1. JSON chứa geometry, edge key, tổng thời
gian gốc, kiểm tra Pareto của hạng 1, spacing và provenance để đối chiếu. Chọn
tên output mới cho mỗi lần chạy; CLI không ghi đè báo cáo cũ và không tải OSM.
Đây là kiểm tra prototype; TC-01–TC-12 chạy trong pytest, còn HTTP, cache,
CSR production và TC-13–TC-16 được nghiệm thu ở các mốc tương ứng.

## Đối chiếu TC-16

```bash
PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.validate_tc16 \
  --bundle-dir backend/data/builds/hanoi-ring3-car-v1-3000-v1/validated \
  --output backend/data/reports/tc16.json
```

CLI mặc định chạy 1.000 request tổng hợp theo seed cố định. Các ca gồm nguồn
gần nhau, phân tán và sát biên AOI. CLI đối chiếu thứ tự điểm và ghi chênh lệch
điểm số, số tuyến kiểm tra và ca sai khác đầu tiên nếu có. Dùng `--requests 6` để chạy
smoke test cả ba nhóm. Mỗi lượt chạy cần một đường dẫn báo cáo mới.

## Cấu trúc mã nguồn

| Đường dẫn | Trách nhiệm |
|---|---|
| `backend/app/main.py` | FastAPI app, CORS, request ID, lỗi, health/readiness |
| `backend/app/api/meeting.py` | API điểm gặp, rerank và cấu hình bản đồ |
| `backend/app/models/` | Validation request và schema response |
| `backend/app/config/` | Settings, polygon nguồn và bảng tốc độ |
| `backend/app/services/area.py` | Polygon, kiểm tra biên và buffer |
| `backend/app/services/graph_geometry.py` | Chuẩn hóa geometry và đo chiều dài |
| `backend/app/services/graph_weights.py` | Parse maxspeed và gán thời gian cạnh |
| `backend/app/services/graph_components.py` | Lọc SCC, xuất phần bị loại trong AOI |
| `backend/app/services/graph_reverse_edges.py` | Nhận diện cặp cạnh ngược |
| `backend/app/services/graph_split.py` | Chia cạnh, xử lý biên AOI và truy vết cạnh gốc |
| `backend/scripts/` | CLI đọc/ghi artifact và gọi các service |
| `backend/tests/` | Test nền tảng, dữ liệu và CLI offline |
| `frontend/app/` | Layout, trang chủ và CSS |
| `frontend/types/meeting.ts` | TypeScript contracts tương ứng models backend |
