# W2M — Where to meet

Ứng dụng tìm điểm gặp cho 4 người trên mạng đường có hướng tại Hà Nội, dựa trên
thời gian di chuyển và mức ưu tiên công bằng của cả nhóm.

**Hiện trạng ngày 2026-11-07:** M0 hoàn thành local. M1 đã có pipeline offline từ
AOI thử nghiệm đến snapshot OSM, chuẩn hóa hình học, gán trọng số `car-v1`, lọc SCC
lớn nhất và nhận diện cặp cạnh ngược. Chưa chia cạnh dài, xuất CSR hoặc nạp graph
vào API. Frontend hiện là trang khởi tạo, chưa gọi backend hoặc hiển thị bản đồ.
Thuật toán tìm điểm gặp, cache/rerank, Docker và nghiệm thu MVP chưa hoàn thành.

- [SPEC v0.2.0](docs/spec/W2M%20—%20Software%20%26%20Technical%20Specification%20v0.2.0.md)
- [Kế hoạch MVP và checklist](docs/plans/W2M-MVP-Plan.md)
- [Bổ sung hợp đồng M0](docs/spec/W2M-M0-Contract-Addendum.md)
- [Hướng dẫn dữ liệu và tái tạo artifact](backend/data/README.md)
- [Development journals](docs/journals/)

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
uv run --project backend --locked uvicorn app.main:app --app-dir backend --reload --port 8000
```

Terminal 2:

```sh
npm --prefix frontend run dev
```

- Frontend: `http://localhost:3000`.
- Swagger/OpenAPI: `http://localhost:8000/docs`.

| Endpoint | Hành vi hiện tại |
|---|---|
| `GET /health` | 200 khi process chạy |
| `GET /ready` | 503 `GRAPH_UNAVAILABLE` |
| `GET /api/v1/map/config` | 503 `GRAPH_UNAVAILABLE` |
| `POST /api/v1/meeting-points` | Validate request; đầu vào hợp lệ trả 503 |
| `POST /api/v1/meeting-points/{request_id}/rerank` | Validate request; đầu vào hợp lệ trả 503 |

Lỗi validation trả 400 `INVALID_COORDINATES` hoặc `INVALID_PARAMETERS`. Các mã lỗi
nghiệp vụ khác và response thành công đã có schema, chưa có đầy đủ xử lý thực tế.
503 là đúng ở trạng thái hiện tại: chưa có graph loader, dù artifact offline đã tồn tại.

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
```

Test backend dùng fixture cố định và OSMnx giả lập cho bước tải; không gọi OSM hoặc
ETA service. Các test roundtrip dùng OSMnx thật để lưu/nạp graph tổng hợp local.
CI tại `.github/workflows/ci.yml` chạy backend Ruff/pytest và frontend
lint/typecheck/build; hiện chưa cài extra `data`, nên không kiểm tra toàn bộ roundtrip.

Bằng chứng local gần nhất:

- Backend: Ruff và **223 test đạt**, không bỏ qua, sau bước nhận diện cạnh ngược
  ngày 2026-11-07. Còn 45 cảnh báo deprecation Shapely/TestClient.
- Frontend: người phát triển đã xác nhận install/audit (0 vulnerabilities),
  lint/typecheck/build và trang chủ hoạt động ở M0; chưa chạy lại trong các task M1.
- Remote CI, frontend E2E và benchmark MVP chưa được xác minh.

## Pipeline dữ liệu offline — M1

```text
Polygon AOI nguồn
  → prepare_aoi           → AOI và routing area có buffer
  → download_osm         → snapshot GraphML thô
  → prepare_graph_geometry → geometry EPSG:32648, chiều dài mét
  → prepare_graph_weights  → tốc độ và thời gian cạnh car-v1
  → prepare_graph_scc       → SCC lớn nhất, GeoJSON phần bị loại
  → prepare_reverse_edges   → ánh xạ cặp cạnh ngược và báo cáo
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
```

Các CLI graph/snapshot từ chối ghi đè thư mục đích: chọn đích mới khi tái tạo và
cập nhật đường dẫn đầu vào của bước sau. Xem [hướng dẫn dữ liệu](backend/data/README.md)
cho quy tắc retry, checksum, cấu trúc metadata và hợp đồng mapping cạnh ngược.

SCC xuất `removed_in_aoi.geojson` gồm 29 node và 37 đoạn cạnh bị loại trong AOI;
chưa rà soát bản đồ trực quan. Mapping cạnh ngược dùng osmid, oneway, thông tin
layer/level/bridge/tunnel và hình học đảo chiều trong 0,01 m; không đổi trọng số
mỗi chiều hoặc tự thêm chiều đi.

## Cấu trúc mã nguồn

| Đường dẫn | Trách nhiệm |
|---|---|
| `backend/app/main.py` | FastAPI app, CORS, request ID, lỗi, health/readiness |
| `backend/app/api/meeting.py` | Các endpoint nghiệp vụ đang chờ tích hợp |
| `backend/app/models/` | Validation request và schema response |
| `backend/app/config/` | Settings, polygon nguồn và bảng tốc độ |
| `backend/app/services/area.py` | Polygon, kiểm tra biên và buffer |
| `backend/app/services/graph_geometry.py` | Chuẩn hóa geometry và đo chiều dài |
| `backend/app/services/graph_weights.py` | Parse maxspeed và gán thời gian cạnh |
| `backend/app/services/graph_components.py` | Lọc SCC, xuất phần bị loại trong AOI |
| `backend/app/services/graph_reverse_edges.py` | Nhận diện cặp cạnh ngược |
| `backend/scripts/` | CLI đọc/ghi artifact và gọi các service |
| `backend/tests/` | Test nền tảng, dữ liệu và CLI offline |
| `frontend/app/` | Layout, trang chủ và CSS |
| `frontend/types/meeting.ts` | TypeScript contracts tương ứng models backend |

## Cấu hình và giới hạn hiện tại

Backend đọc `.env` gốc với prefix `W2M_`; xem [.env.example](.env.example). Cấu hình
bao gồm đường dẫn dữ liệu, buffer, snap radius, access speed, cutoff và cache.
Các tham số snap/cache đã được khai báo nhưng xử lý runtime chưa triển khai.

Frontend đọc `frontend/.env.local`; xem [mẫu cấu hình](frontend/.env.example).
`NEXT_PUBLIC_API_BASE_URL` và `NEXT_PUBLIC_MAP_STYLE_URL` dành cho bước tích hợp
sau. Mọi biến `NEXT_PUBLIC_*` đều công khai; không đặt secret vào đó. MapLibre đã
có dependency nhưng chưa được dùng để hiển thị bản đồ, chưa chọn tile provider.

- Bước kế tiếp: chia cạnh trên 60 giây, đồng bộ vị trí chia hai chiều và xử lý biên
  AOI; sau đó gắn cờ ứng viên, xuất CSR và hoàn thiện validation M1.
- Graph SCC vẫn có cạnh tối đa 140,494 giây; chưa đạt ngưỡng sau chia 60 giây.
- `car-v1` là tốc độ giả định, chưa hiệu chỉnh. Mô hình chưa xét cấm rẽ, chi phí rẽ
  hoặc giao thông thời gian thực; kết quả sau này là thời gian ước lượng.
- Chưa có snapping/Dijkstra/OWA phục vụ request, cache/rerank hoặc Docker runtime.
- Không log request body chứa tọa độ; không lưu tọa độ người dùng vào artifact.

Dữ liệu đường từ © OpenStreetMap contributors, ODbL-1.0; attribution và license
được lưu trong artifact. Cần rà soát điều kiện phân phối dữ liệu dẫn xuất và
điều khoản tile provider trước khi triển khai công khai.

Frontend hiện giữ override `@typescript-eslint/typescript-estree` → minimatch
`^11.0.1` từ lần xử lý audit M0; cần kiểm tra tương thích lint khi đổi dependency
và bỏ override khi dependency upstream phù hợp. Kết quả audit M0 là bằng chứng
lịch sử, chưa phải xác nhận bảo mật tại thời điểm cài đặt mới.


**IMPORTANT: AI CODE ĐÉO PHẢI TÔI !!!**