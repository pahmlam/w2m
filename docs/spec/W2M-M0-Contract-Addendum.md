# W2M — Bổ sung hợp đồng kỹ thuật M0

**Ngày:** 2026-11-06  
**Áp dụng:** đặc tả v0.2.0 và kế hoạch MVP. Bản đặc tả gốc được giữ để truy vết;
các quy tắc dưới đây làm rõ hoặc thay thế các mục được chỉ ra.

## 1. Thứ tự xếp hạng và Pareto

Thay khóa xếp hạng tại mục 3.6 bằng:

```text
(q(Score), q(T_max), q(T_avg), tuple(sorted(T_raw, reverse=True)), node_id)
```

`T_raw = access_raw + shortest_path_raw`; Score vẫn tính từ các thời gian đã lượng tử.
Vector gốc chỉ phá hòa trước node ID, không thay công thức OWA. Nếu một điểm trội
hơn điểm khác, các tiêu chí đã lượng tử không thể tệ hơn; khi chúng hòa, vector gốc
đã sắp xếp xác định đúng thứ tự. Cách này giữ đối xứng giữa nhãn A–D.

Ví dụ node 2 có `(100,100,100,100)` và node 1 có `(100.01,100,100,100)`:
khóa cũ chọn node 1 khi các chỉ số lượng tử hòa; khóa bổ sung chọn node 2.
Frontend hiển thị theo `rank`, không tự sắp xếp theo score đã làm tròn.
Chỉ hạng 1 được bảo đảm Pareto toàn cục trên tập ứng viên; các hạng sau chịu lọc spacing.

TC-08/TC-09 kiểm tra tính chất chặt của scorer gốc. Kiểm thử xếp hạng production
phải kiểm tra thêm trường hợp khác nhau dưới 0,1 giây và node ID bất lợi.

## 2. Node ứng viên và hình học

Node bền vững sau tiền xử lý, gồm node chia cạnh, được làm ứng viên trong AOI.
Nguồn overlay chỉ sống trong request bị loại khỏi tập ứng viên. Điểm trên biên AOI
được chấp nhận (`covers`); các phép đo khoảng cách dùng EPSG:32648.
Cặp cạnh ngược phải thuộc cùng đoạn đường vật lý, không chỉ có đầu mút đảo chiều.

GeoJSON API dùng `[longitude, latitude]`; geometry tuyến chạy từ điểm snap đến điểm gặp.
Đoạn tiếp cận là lớp riêng. `distance_meters` chỉ tính chiều dài mạng đường.
Tuyến 0 mét có LineString gồm hai tọa độ trùng nhau để giữ hợp đồng GeoJSON.

## 3. Thời gian và lượng tử

`q(x) = round(10*x)/10`, round half to even. Tính toán nội bộ dùng float64.
Lọc cutoff trên thời gian gốc trước lượng tử; không nhận một điểm vượt giới hạn
chỉ vì thời gian hiển thị được làm tròn xuống.

Kiểm tra `sum(edge_times)` với khoảng cách Dijkstra gốc theo sai số mục 3.6.
Các trường API biểu diễn bằng decisecond, tính theo số nguyên trước serialize:

```text
duration_ticks = round(10 * (access_raw + network_raw))
access_ticks = round(10 * access_raw)
network_ticks = duration_ticks - access_ticks
```

Chia tick cho 10 khi trả JSON. `duration_seconds` bằng `travel_times[id]`;
access + network bằng duration theo đơn vị decisecond. Network hiển thị có thể
lệch đến 0,1 giây so với thời gian mạng gốc; không dùng nó cho kiểm tra tổng cạnh.
`timings_ms` là số đo milliseconds, không áp dụng lượng tử giây. Weights không
làm tròn còn bốn chữ số khi dùng tính toán/kiểm chứng.

TC-03 kiểm tra scorer chưa lượng tử tại khoảng `10.750 / 11.263 / 11.890`;
API tương ứng `10.8 / 11.3 / 11.9`.

## 4. Request và rerank

Giữ request tạo mới theo mục 7.1. Thiếu `optimization` dùng mặc định spec;
nếu có thì các trường thiếu cũng dùng mặc định runtime từ Settings. Khi không
ghi đè môi trường, các giá trị theo v0.2.0; map config phải dùng cùng Settings.

Rerank dùng body đầy đủ về mặt cấu trúc như sau (không gửi lại origins):

```json
{
  "optimization": {
    "phi": 0.7,
    "max_travel_seconds": 3600,
    "top_k": 5,
    "min_spacing_meters": 500
  }
}
```

Rerank là thay thế optimization, không phải PATCH. Thiếu trường dùng mặc định,
không ngầm lấy từ lần rerank trước. Tăng vượt cutoff của lần tính gốc trả 409;
giảm rồi tăng lại trong dữ liệu đã cache vẫn có thể tái sử dụng. TTL 900 giây tính
từ lần tính gốc, không gia hạn do kéo slider. Cache không lưu xuống đĩa.

ID nguồn là chuỗi không rỗng, duy nhất, tối đa 64 ký tự; A–D là nhãn UI mặc định.
Chấp nhận nguồn trùng tọa độ. API từ chối trường lạ để phát hiện client sai hợp đồng.
Lỗi validation trả 400: lỗi `lat`/`lon` là `INVALID_COORDINATES`, lỗi khác là
`INVALID_PARAMETERS`. Không echo tọa độ vào response lỗi hoặc log.

Request ID trong response lỗi và header `X-Request-ID` là ID xử lý HTTP hiện tại;
`MeetingResponse.request_id` khi thành công xác định bộ dữ liệu dùng để rerank.

## 5. Map config

Hợp đồng `GET /api/v1/map/config` được định nghĩa tại model `MapConfig` ở hai phía:

- `aoi`: GeoJSON Polygon (không bọc Feature).
- `travel_modes`: `["car"]`.
- `limits`: min/max cho phi, max_travel_seconds, top_k, min_spacing_meters.
- `defaults`: bốn trường Optimization và `v_access` tính bằng m/s.
- `graph_version`, `weight_profile_version`, `source_date` (ISO date).

Chưa có AOI/graph thì trả 503, không trả polygon minh họa như dữ liệu thật.
Empty response có `error_code: NO_COMMON_REACHABLE_NODE`; `min_required_seconds`
là số nếu biết chính xác, chuỗi `"> 3600"` nếu cutoff chỉ cho biết cận dưới.

## 6. Trạng thái tại M0

`GET /health` trả 200 khi process chạy; `GET /ready` trả 503 vì chưa nạp graph.
Ba endpoint nghiệp vụ được đăng ký để kiểm tra OpenAPI/validation nhưng đều trả
`GRAPH_UNAVAILABLE` sau validation. M1–M4 sẽ cung cấp dữ liệu và hành vi thật.
Chưa chạy TC-01–TC-16; test fixture M0 không thay thế các cổng nghiệm thu đó.
