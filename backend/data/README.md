# Dữ liệu runtime

Nguồn AOI thử nghiệm được version trong `backend/app/config/areas/hanoi-pilot-v1.geojson`.
Từ thư mục gốc, chạy:

```sh
PYTHONPATH=backend uv run --project backend --locked python -m scripts.prepare_aoi
```

Lệnh này không tải OSM. Nó kiểm tra polygon và tạo:

- `aoi.geojson`: Polygon WGS84 cho kiểm tra đầu vào và ứng viên.
- `routing_area.geojson`: Polygon WGS84 sau buffer 3.000 m trên EPSG:32648.
- `aoi.metadata.json`: ID, hash nguồn, CRS, buffer, diện tích mét vuông và bounds.

Đầu ra ghi đè các artifact cùng đường dẫn nếu đã tồn tại. Không cho phép đường dẫn
nguồn trùng với đầu ra; kiểm tra cấu hình trước khi chạy. Khi lỗi ghi file, không
sử dụng bộ artifact chưa xuất đủ cả ba file.

Chỉnh source/output bằng Settings `W2M_AOI_SOURCE_PATH`, `W2M_AOI_PATH`,
`W2M_ROUTING_AREA_PATH`; buffer bằng `W2M_BUFFER_M`. Có thể ghi đè bằng CLI:
`--source`, `--aoi-output`, `--routing-output`, `--metadata-output`, `--buffer-m`.
Đường dẫn tương đối được tính từ thư mục làm việc, vì vậy chạy từ thư mục gốc.

Vùng thử nghiệm có bounds `[105.84, 21.02, 105.86, 21.04]`, tọa độ `[lon, lat]`.
Đây là hình chữ nhật kỹ thuật để thử pipeline, chưa phải ranh giới hành chính
hoặc AOI toàn nội đô Vành đai 3 đã được rà soát. Điểm trên biên được chấp nhận
bằng `covers`; phần nằm trong lỗ polygon bị loại. Routing area không mở rộng
phạm vi đầu vào. Buffer dùng 64 đoạn mỗi góc phần tư; cung tròn được xấp xỉ đa giác.

Không đưa artifact lớn hoặc tọa độ người dùng vào Git. Nguồn polygon nhỏ được theo
dõi trong config; các file sinh tại đây được `.gitignore` bỏ qua.
Các bước M1 sau sẽ tạo `graph/` cùng metadata, CSR và geometry. Chỉ có AOI chưa
làm backend sẵn sàng: readiness/API vẫn trả 503 đến khi tích hợp bộ nạp đồ thị.

Tham khảo API: [pyproj Transformer](https://pyproj4.github.io/pyproj/stable/api/transformer.html),
[Shapely buffer](https://shapely.readthedocs.io/en/stable/reference/shapely.buffer.html),
[Shapely covers](https://shapely.readthedocs.io/en/stable/reference/shapely.covers.html).

## Snapshot OSM offline

Sau khi đã sinh `routing_area.geojson`, người phát triển chạy từ thư mục gốc:

```sh
uv run --project backend --locked ruff check backend
uv run --project backend --locked pytest backend/tests
uv sync --project backend --locked --extra data
PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.download_osm
```

`data` là optional extra đã có trong manifest/lockfile; script không cần thay
dependency. Test dùng module OSMnx giả lập, không cần extra này và không gọi OSM.
Chỉ lệnh download cuối truy cập mạng. Sau bổ sung retry, người phát triển xác nhận
Ruff và 72 test đạt; tải thật thành công. Còn 11 cảnh báo deprecation đã biết.

Snapshot hiện có: `backend/data/osm/drive-20261106T092834Z/`. Manifest đã được đọc:
21.129 node, 36.912 cạnh, CRS `epsg:4326`, cutoff `2026-11-06T09:28:34Z`,
OSMnx 2.1.1, 1 lần gọi tải và 1 file cache. Snapshot này làm đầu vào local cho
bước tiền xử lý tiếp theo; không cần tải lại để bắt đầu xây đồ thị.

Mặc định dùng `W2M_ROUTING_AREA_PATH` và tạo thư mục mới
`backend/data/osm/drive-<UTC timestamp>/` (đổi thư mục cha bằng `W2M_OSM_SNAPSHOT_DIR`).
Script in đường dẫn snapshot và manifest khi thành công. Mỗi thư mục gồm:

- `graph.graphml`: MultiDiGraph WGS84 chưa simplify, chưa lọc SCC/chia cạnh/gán tốc độ.
- `routing_area.geojson`: bản sao đúng polygon dùng truy vấn; không phụ thuộc file nguồn thay đổi sau đó.
- `responses/`: cache JSON phản hồi Overpass do OSMnx lưu để truy vết dữ liệu tải.
- `manifest.json`: snapshot ID, nguồn/ngày dữ liệu, cutoff, thời gian tải, endpoint,
  cấu hình graph, phiên bản OSMnx, số node/cạnh, checksum và attribution.

Lấy mạng `drive`, `simplify=False`, `retain_all=True`, `truncate_by_edge=False`.
Giữ thành phần rời rạc để báo cáo phần bị loại ở bước SCC sau; không ép đường
ô tô thành hai chiều. Giữ tag highway/maxspeed/oneway và các tag liên quan cho
bước xây trọng số. GraphML được nạp lại offline để kiểm tra kiểu graph và số lượng
node/cạnh trước khi công bố snapshot. Đây chưa phải đồ thị production.

Tất cả truy vấn trong một lần tải dùng cùng cutoff Overpass. Mặc định cutoff là
thời điểm bắt đầu lệnh theo UTC; `source_date` là ngày UTC của cutoff yêu cầu,
không phải ngày cập nhật mới nhất của từng phần tử OSM. Có thể chỉ định lịch sử:

```sh
PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.download_osm \
  --snapshot-at 2026-11-06T00:00:00Z \
  --output-dir backend/data/osm/hanoi-pilot-20261106
```

`--snapshot-at` phải có timezone, không ở tương lai. `--routing-area` ghi đè polygon
đầu vào. Snapshot có sẵn sẽ không bị ghi đè; chọn thư mục đầu ra khác khi cần tải mới.
Thư mục tạm được đổi tên thành snapshot sau khi lưu và reload thành công; nếu lỗi
thì không công bố snapshot thiếu file. Cache tạm cũng bị dọn khi lệnh thất bại.
Lệnh tôn trọng cơ chế rate limit Overpass của OSMnx; mặc định request timeout 180 giây.
Khi lỗi mạng, có thể chạy lại với một thư mục mới hoặc đích chưa được tạo thành công.

Lỗi `ResponseStatusCodeError` của OSMnx với HTTP 500/502/503 được thử lại tối đa
4 lần gọi tải tổng cộng, chờ 10, 20, 40 giây giữa các lần. Giữ nguyên cutoff và
cache trong staging qua các lần retry; manifest ghi `download_attempts` khi thành công.
Lỗi validation, HTTP 400/403 hoặc lỗi không nhận diện được sẽ báo lỗi ngay.
Retry chỉ bọc bước tải, không chạy lại thao tác ghi/reload GraphML khi ghi file lỗi.
Cơ chế đợi slot và retry nội bộ 429/504 của OSMnx vẫn giữ nguyên, nên giới hạn
4 lần này không phải giới hạn tổng số request HTTP hoặc thời gian toàn bộ lệnh.

Tham khảo cách OSMnx tạo lỗi HTTP tại
[`_http._parse_response` v2.1.1](https://github.com/gboeing/osmnx/blob/v2.1.1/osmnx/_http.py)
và xử lý Overpass tại
[`_overpass` v2.1.1](https://github.com/gboeing/osmnx/blob/v2.1.1/osmnx/_overpass.py).

API và startup không gọi script này. Sau khi có snapshot, các bước xử lý tiếp theo
đọc GraphML local; không tải lại OSM. Các snapshot/cache thuộc data được ignore,
không chứa vị trí do người dùng gửi lên ứng dụng.

Tham khảo: [OSMnx graph_from_polygon](https://osmnx.readthedocs.io/en/stable/user-reference.html#osmnx.graph.graph_from_polygon),
[OSMnx save/load GraphML](https://osmnx.readthedocs.io/en/stable/user-reference.html#osmnx.io.save_graphml),
[OSMnx settings](https://osmnx.readthedocs.io/en/stable/user-reference.html#osmnx.settings-module).

## Chuẩn hóa hình học offline — M1

Sau khi cài extra `data`, chạy từ thư mục gốc (không gọi mạng):

```sh
PYTHONPATH=backend uv run --project backend --locked --extra data python -m scripts.prepare_graph_geometry \
  --snapshot-dir backend/data/osm/drive-20261106T092834Z \
  --output-dir backend/data/geometry/drive-20261106T092834Z-utm-v1
```

CLI kiểm tra checksum snapshot, xử lý trên bản sao và xuất thư mục mới sau khi
kiểm tra GraphML nạp lại. Không ghi đè snapshot hoặc thư mục đầu ra đã tồn tại.

- Node giữ WGS84 trong `lon/lat`; `x/y` và geometry cạnh dùng EPSG:32648.
- Cạnh thiếu geometry được nối từ hai đầu mút; geometry có sẵn giữ đường cong,
  đảo thứ tự tọa độ khi cần để theo chiều nguồn → đích.
- Hai đầu geometry phải khớp node trong ngưỡng 0,01 m; sai lệch nhỏ trong ngưỡng
  được đưa về đúng tọa độ node để ghép tuyến không có khe hở.
- `length_m` và `length` đều là chiều dài hình học đã chiếu, đơn vị mét.
  Dữ liệu sai CRS, tọa độ lỗi, geometry rỗng/sai kiểu/sai đầu mút hoặc chiều dài
  không dương sẽ báo lỗi kèm node/cạnh; không âm thầm bỏ cạnh.
- Giữ nguyên hướng, cạnh song song, thuộc tính OSM và topology.
- `metadata.json` ghi stage `geometry-only`, checksum nguồn/đầu ra, CRS, số
  node/cạnh, thống kê chiều dài và attribution/license của snapshot.

Đã chạy trên snapshot thật: 21.129 node, 36.912 cạnh; chiều dài nhỏ nhất
0,094 m, lớn nhất 1.170,781 m. Ruff và 94 test backend đạt, gồm 22 test mới;
test roundtrip OSMnx được bỏ qua nếu môi trường chưa cài extra `data`.
Có 18 cảnh báo deprecation Shapely/TestClient trong lần chạy này.

Artifact này chưa lọc SCC, gán tốc độ/thời gian, chia cạnh hoặc xuất CSR.
Chưa tích hợp runtime và không làm readiness chuyển sang 200.
