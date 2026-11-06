# W2M — Kế hoạch triển khai và nghiệm thu MVP

**Căn cứ:** [Software & Technical Specification v0.2.0](../spec/W2M%20—%20Software%20%26%20Technical%20Specification%20v0.2.0.md)  
**Ngày lập:** 2026-11-06  
**Trạng thái:** M0 hoàn thành local; CI remote chưa được xác minh. M1 đã có AOI thử nghiệm, buffer 3 km và snapshot OSM thật `drive-20261106T092834Z`; Đã chuẩn hóa hình học EPSG:32648 trên snapshot thật; Ruff và 94 test backend đạt trong task chuẩn hóa hình học. AOI toàn nội đô và các bước tiền xử lý đồ thị M1 còn lại chưa hoàn thành; M2–M6 chưa thực hiện.

## 1. Mục tiêu và các quyết định đã chốt

Hoàn thành ứng dụng chạy đầy đủ bằng Docker trên máy local: người dùng đặt 4 vị trí tại Hà Nội, tìm tối đa 5 điểm gặp và xem 4 tuyến đường tương ứng. Ứng dụng phải vượt các kiểm thử chức năng, tính đúng đắn và hiệu năng; có tài liệu để triển khai công khai sau đó.

Tại thời điểm lập kế hoạch, repo chỉ có tài liệu, chưa có backend hoặc frontend. Kế hoạch bắt đầu từ khởi tạo dự án.

### Quy ước checklist

- `[ ]` là công việc hoặc tiêu chí chưa hoàn thành.
- Chỉ đánh dấu hoàn thành khi có mã nguồn, dữ liệu, kết quả kiểm thử hoặc tài liệu chứng minh tương ứng.
- Mỗi mốc có điều kiện nghiệm thu; không bỏ qua kiểm thử để chuyển mốc.
- Triển khai công khai là checklist riêng, không chặn nghiệm thu MVP local.

### Cấu hình mặc định

| Thuộc tính | Mặc định |
|---|---|
| Số người | Chính xác 4; lõi thuật toán hỗ trợ K nguồn |
| Phương tiện | Ô tô |
| Khu vực | Polygon nội đô Hà Nội theo định hướng Vành đai 3 |
| Vùng định tuyến | AOI mở rộng 3.000 m; tăng nếu TC-15 không đạt |
| Thời gian tối đa | 3.600 giây/người, gồm thời gian tiếp cận |
| Mức công bằng | `phi = 0.5`, slider bước `0.1` |
| Kết quả | Tối đa 5 điểm |
| Khoảng cách giữa kết quả | 500 m, đo trên EPSG:32648 |
| Bán kính snap | 150 m |
| Tốc độ tiếp cận | 1,4 m/s |
| Thời gian cạnh sau chia nhỏ | Không quá 60 giây |
| Cache | In-memory LRU, TTL 15 phút, có giới hạn bộ nhớ |
| Định tuyến production | CSR + SciPy; NetworkX làm bản tham chiếu |
| Dừng sớm | Chưa bật trong MVP |
| Chạy local | Một backend instance, một API worker |

### Các điểm phải chuẩn hóa trước khi triển khai

- [ ] **Bảo toàn Pareto sau lượng tử**, theo lựa chọn của chủ dự án. Dùng khóa xếp hạng:

  ```text
  (
    q(Score),
    q(T_max),
    q(T_avg),
    tuple(sorted(T_raw, reverse=True)),
    node_id
  )
  ```

  Vector thời gian gốc được dùng trước node ID để tránh một điểm bị trội thắng do làm tròn. Vector này chỉ dùng nội bộ; frontend sử dụng `rank` do backend trả về.

- [ ] **Thống nhất tập ứng viên:** mọi node tồn tại lâu dài trong đồ thị sản xuất sau tiền xử lý, gồm node tạo khi chia cạnh, đều có thể là ứng viên nếu nằm trong AOI. Nguồn tạm của request không phải ứng viên.
- [ ] **Tách kiểm thử toán học và kiểm thử API:** TC-03, TC-08, TC-09 kiểm tra tính chất của hàm chưa lượng tử; bổ sung kiểm thử riêng cho thứ hạng và số liệu sau lượng tử.
- [ ] **Thống nhất làm tròn tuyến:** kiểm tra tổng trọng số bằng số thực gốc; biểu diễn API theo decisecond. `duration_seconds = q(access_raw + network_raw)`, `access_seconds = q(access_raw)`, còn `network_seconds` là phần dư để tổng hai thành phần bằng duration. Ghi rõ sai lệch biểu diễn có thể đến 0,1 giây so với thời gian mạng gốc.
- [ ] **Thống nhất khoảng cách tuyến:** `distance_meters` là chiều dài tuyến trên mạng đường; khoảng cách tiếp cận được trả riêng qua `snap_distance_m`.
- [ ] **Thống nhất acceptance về khoảng cách:** tiêu chí cách nhau ít nhất 500 m áp dụng cấu hình mặc định; API vẫn nhận miền giá trị tùy chỉnh ở mục 7.1 của đặc tả.
- [ ] Ghi các bổ sung này thành quyết định kỹ thuật và đồng bộ với bản đặc tả Draft trước khi viết kiểm thử nghiệm thu.

Phạm vi MVP giữ theo Phase 1–2 của đặc tả. Xe máy, địa điểm kinh doanh, giao thông thời gian thực, cấm rẽ, chi phí rẽ và điểm gặp liên tục giữa cạnh thuộc giai đoạn sau.

## 2. Checklist triển khai theo mốc

Thứ tự phụ thuộc chính: **M0 → M1 → M2 → M3 → M4 → M5 → M6 → nghiệm thu**. Kiểm thử từng phần được thực hiện trong chính mốc tương ứng, không dồn toàn bộ đến cuối.

### M0 — Khởi tạo dự án và khóa hợp đồng

**Đầu ra:** môi trường phát triển tái lập được và hợp đồng dữ liệu rõ ràng.

- [x] Khởi tạo cấu trúc backend FastAPI và frontend Next.js/TypeScript theo đặc tả.
- [x] Thiết lập Git, `.gitignore`; cấu hình bỏ qua môi trường ảo, cache, secret và dữ liệu đồ thị lớn. Đã kiểm tra `.git` và nội dung `.gitignore`; không thực hiện commit trong task này.
- [x] Chọn phiên bản runtime tương thích và khóa dependency cho cả backend, frontend. Python 3.12/Node 22 được chọn; `backend/uv.lock` và `frontend/package-lock.json` đã có. Backend chạy `--locked`, frontend install/audit/lint/typecheck/build đạt theo output người phát triển.
- [x] Thiết lập lệnh chạy dev, kiểm thử, lint, typecheck và build.
- [x] Khai báo cấu hình AOI, buffer, speed profile, snap, access speed, cutoff, cache và URL backend.
- [x] Tạo cấu hình môi trường mẫu; mô tả biến bắt buộc, mặc định và cách cấp giá trị.
- [x] Định nghĩa request/response theo mục 7 của đặc tả; cập nhật các quy tắc chuẩn hóa tại [bổ sung M0](../spec/W2M-M0-Contract-Addendum.md).
- [x] Chuẩn bị đồ thị kiểm thử nhỏ: đường một chiều, cạnh song song, hai chiều có tốc độ khác nhau, nguồn trùng và node không tới được.
- [x] Thiết lập CI chạy kiểm thử nhỏ, lint, typecheck và build; không tải OSM trực tiếp trong CI thông thường. Hai lockfile đã có; chưa xác minh workflow trên remote.
- [x] Viết hướng dẫn khởi động môi trường phát triển.

**Cổng nghiệm thu M0**

- [x] Backend khởi động được; frontend build được. Frontend production build đã đạt với Next.js 16.4.5; Uvicorn startup thành công, `/health` trả 200, `/ready` và `/api/v1/map/config` trả 503 `GRAPH_UNAVAILABLE` đúng kỳ vọng M0. Request ID header/body lỗi khớp nhau theo output người phát triển cung cấp ngày 2026-11-06.
- [x] Các kiểm tra nền tảng chạy bằng lệnh được ghi trong tài liệu. Người phát triển xác nhận Ruff, 26 pytest, frontend lint/typecheck/build đạt; audit 0 vulnerabilities.
- [x] Hợp đồng API và các quyết định bổ sung đã được rà soát ở phạm vi M0, ghi rõ tại [bổ sung M0](../spec/W2M-M0-Contract-Addendum.md). Các kiểm tra nền tảng đã đạt; thuật toán và TC-01–TC-16 vẫn thuộc các mốc sau, không được coi là đã triển khai.

**Xác nhận bổ sung:** người phát triển xác nhận trang chủ frontend tại `http://localhost:3000` đã hiển thị. M0 hoàn thành ở môi trường local; cảnh báo deprecation TestClient/httpx còn được theo dõi.

### M1 — Dữ liệu bản đồ và đồ thị offline

**Đầu ra:** bộ đồ thị có phiên bản, đủ dữ liệu để snap, định tuyến và dựng hình học.

**Tiến độ bước AOI:**

- [x] Định nghĩa nguồn polygon nhỏ `hanoi-pilot-v1.geojson` trong config để theo dõi phiên bản; đây là AOI kỹ thuật thử nghiệm, chưa phải ranh giới AOI toàn nội đô đã được rà soát.
- [x] Viết validation GeoJSON, kiểm tra biên bằng `covers`, buffer EPSG:32648, CLI xuất geometry/metadata và các test offline.
- [x] Người phát triển chạy Ruff, pytest và CLI: Ruff đạt, 51 test đạt (25 AOI + 26 nền tảng), CLI xuất đủ AOI/routing area/metadata. Đã đọc metadata đầu ra: CRS đo EPSG:32648, geometry EPSG:4326, buffer 3.000 m, boundary `covers`; chưa rà soát bản đồ trực quan hoặc ranh giới toàn nội đô.

- [ ] Tạo polygon AOI hợp lệ; rà soát ranh giới theo phạm vi nội đô đã chọn. Dùng vùng nhỏ để thử trước, dùng AOI đầy đủ khi nghiệm thu.
- [ ] Quy định điểm nằm trên biên AOI được chấp nhận; dùng cùng quy tắc ở backend và frontend.
- [x] Tạo `ROUTING_AREA` bằng buffer trên EPSG:32648 cho AOI thử nghiệm. Artifact đã được CLI xuất với buffer 3.000 m; diện tích AOI khoảng 4,60 km², routing area khoảng 58,62 km² theo metadata. Cần sinh lại khi thay AOI đầy đủ.
**Tiến độ bước tải OSM:**

- [x] Viết `scripts.download_osm` tải `drive` chưa simplify, giữ mọi thành phần và cạnh song song; lưu GraphML, polygon truy vấn, cache phản hồi và manifest có cutoff/checksum. Thêm test giả lập OSMnx, không gọi mạng trong CI.
- [x] Bản tải ban đầu qua Ruff và 64 test backend theo output người phát triển; optional extra data cài thành công với OSMnx 2.1.1.
- [x] Bổ sung retry HTTP 500/502/503 tối đa 4 lần gọi tải, backoff 10/20/40 giây, giữ cutoff/cache; thêm test giả lập retry và cleanup.
- [x] Người phát triển chạy lại Ruff/pytest sau sửa retry: Ruff đạt, 72/72 test đạt (11 cảnh báo deprecation). Tải thật thành công với OSMnx 2.1.1; đã đọc manifest `drive-20261106T092834Z`: cutoff `2026-11-06T09:28:34Z`, 21.129 node, 36.912 cạnh, WGS84, 1 lần gọi tải và 1 file cache phản hồi. Snapshot được script nạp lại trước khi công bố; chưa xác minh đồ thị production.

- [x] Tải dữ liệu OSM offline bằng cấu hình `drive`; lưu nguồn, thời điểm dữ liệu và thông tin tái tạo. Snapshot thật nằm tại `backend/data/osm/drive-20261106T092834Z/`, có GraphML, polygon, cache và manifest/checksum.
- [x] Dựng MultiDiGraph thô có hướng; giữ cấu trúc một chiều và cạnh song song qua GraphML. Snapshot đã được lưu/nạp lại bằng OSMnx; chưa simplify, chiếu hệ tọa độ, gán trọng số hoặc lọc SCC.
- [x] Chuẩn hóa hình học cạnh theo chiều `u → w`; đo lại chiều dài trên EPSG:32648. Module `graph_geometry` và CLI `scripts.prepare_graph_geometry` đã qua Ruff, 94 test backend (22 test mới); chạy offline trên snapshot thật và kiểm tra GraphML sau nạp lại. Artifact `backend/data/geometry/drive-20261106T092834Z-utm-v1/` giữ nguyên 21.129 node/36.912 cạnh; chiều dài từ 0,094 đến 1.170,781 m, đều dương. Đây mới là artifact hình học, chưa phải graph production.
- [ ] Cài đặt speed profile: tra `highway`, lấy tốc độ thấp nhất khi là danh sách, dùng `default` khi không nhận diện được.
- [ ] Cài đặt parser `maxspeed`: km/h, mph, danh sách, dữ liệu chữ hoặc không hợp lệ; chỉ dùng làm cận trên.
- [ ] Kiểm tra chiều dài, tốc độ và thời gian cạnh hữu hạn, dương; báo cáo dữ liệu bị loại hoặc phải sửa.
- [ ] Giữ SCC lớn nhất; xuất số node/cạnh bị loại và bản đồ vùng bị loại trong AOI.
- [ ] Xác định cặp cạnh ngược chiều cùng đoạn đường bằng dữ liệu và hình học; không suy luận chỉ từ hai đầu mút.
- [ ] Chia cạnh có thời gian trên 60 giây; giữ nguyên tổng chiều dài, tổng thời gian và chiều đi. Cạnh hai chiều cùng đoạn đường dùng các vị trí chia tương ứng.
- [ ] Xử lý giao với biên AOI khi chia cạnh để xác định đúng node và đoạn đường thuộc phạm vi hỗ trợ.
- [ ] Cấp ID tất định cho node/cạnh sinh thêm; kiểm tra SCC sau chia cạnh.
- [ ] Gắn cờ ứng viên trong AOI; hỗ trợ đọc danh sách loại trừ nếu có dữ liệu.
- [ ] Khi xuất CSR, chọn cạnh nhỏ nhất theo `(travel_time, edge_key)` cho mỗi cặp có hướng; không để thư viện cộng trọng số cạnh song song.
- [ ] Lưu ánh xạ node ID ↔ chỉ số mảng và cung CSR ↔ cạnh/hình học gốc.
- [ ] Xuất đồ thị tham chiếu, CSR `.npz`, geometry, AOI và metadata có cùng phiên bản.
- [ ] Chuẩn bị geometry để dựng STRtree khi backend khởi động.
- [ ] Tạo báo cáo validation: P50/P99/max thời gian cạnh, số cạnh dùng tốc độ mặc định, SCC, kích thước đồ thị và kiểm tra tuyến mẫu với NetworkX.
- [ ] Ghi đủ metadata mục 10.4 của đặc tả, gồm `graph_version` và `weight_profile_version`.

**Cổng nghiệm thu M1**

- [ ] Đồ thị nạp lại được từ artifact mà không tải OSM.
- [ ] Không có cạnh sai đơn vị, trọng số không hợp lệ hoặc ánh xạ CSR thiếu hình học.
- [ ] Các đoạn sau chia đáp ứng ngưỡng 60 giây.
- [ ] Có báo cáo rà soát phạm vi AOI và vùng bị loại bởi SCC.

### M2 — Prototype thuật toán tham chiếu

**Đầu ra:** pipeline đúng bằng Python/NetworkX, làm chuẩn cho bản tối ưu.

- [ ] Xác thực đúng 4 nguồn, ID duy nhất, tọa độ hữu hạn và nằm trong AOI; cho phép vị trí trùng nhau.
- [ ] Chiếu tọa độ nhất quán, tránh đảo latitude/longitude.
- [ ] Snap bằng STRtree trong bán kính 150 m; xử lý hòa bằng ID tất định.
- [ ] Ghi điểm chiếu, cạnh được chọn, `theta`, khoảng cách snap và thời gian tiếp cận.
- [ ] Tạo overlay riêng cho request; nguồn tạm chỉ có cạnh ra đúng chiều. Khi snap vào đầu mút thì dùng node có sẵn.
- [ ] Xử lý đúng cạnh hai chiều có thời gian hai chiều khác nhau và nhiều nguồn cùng nằm trên một cạnh.
- [ ] Chạy Dijkstra riêng cho từng nguồn với cutoff `T_LIMIT − access_raw`.
- [ ] Lưu khoảng cách và predecessor có đủ edge key; giữ nguyên đồ thị dùng chung.
- [ ] Lọc ứng viên theo thời gian gốc trước khi lượng tử, tránh nhận điểm thực tế vượt cutoff.
- [ ] Cài đặt trọng số OWA và scorer tổng quát cho K nguồn; trọng số được tính đủ độ chính xác.
- [ ] Lượng tử thời gian và score theo bước 0,1 giây; dùng quy tắc round thống nhất.
- [ ] Xếp hạng theo khóa đã bổ sung; kiểm tra tính đối xứng khi đổi nhãn A–D.
- [ ] Lọc đa dạng tham lam trên EPSG:32648; không nới khoảng cách khi thiếu kết quả.
- [ ] Dựng tuyến từ predecessor của chính lần Dijkstra đã xếp hạng, gồm cả phần cạnh từ nguồn tạm.
- [ ] Ghép polyline từ hình học cạnh thực; xử lý tuyến dài bằng 0 bằng LineString có hai tọa độ trùng nhau.
- [ ] Tính khoảng cách mạng, kiểm tra tổng trọng số gốc và chuẩn hóa các trường thời gian API.
- [ ] Chạy TC-01 đến TC-12 và các kiểm thử bổ sung về lượng tử.

**Cổng nghiệm thu M2 — Phase 1 hoàn thành**

- [ ] TC-01–TC-12 đạt.
- [ ] Có thể chạy một request trên đồ thị thử nghiệm Hà Nội và xuất kết quả kiểm tra được.
- [ ] Điểm hạng 1 không bị ứng viên hợp lệ nào trội hơn.
- [ ] Mọi tuyến khớp thời gian nội bộ trong sai số đặc tả.

### M3 — Định tuyến production bằng CSR

**Đầu ra:** pipeline production dùng CSR, tương đương bản tham chiếu.

- [ ] Nạp CSR và các ánh xạ vào bộ nhớ; bảo vệ dữ liệu nền khỏi sửa đổi trong request.
- [ ] Tạo CSR overlay riêng cho request bằng cách bổ sung tối đa 4 nguồn tạm; không sửa CSR dùng chung.
- [ ] Chạy SciPy Dijkstra ở chế độ có hướng, 4 lần với cutoff riêng của từng nguồn.
- [ ] Khôi phục đúng cạnh từ predecessor và bảng ánh xạ, kể cả cạnh song song.
- [ ] Dùng cùng quy tắc lọc ứng viên, chấm điểm, lượng tử và xếp hạng với bản tham chiếu.
- [ ] Chỉ dựng geometry cho các điểm đã được chọn.
- [ ] Đưa công việc CPU ra khỏi event loop; giới hạn số tác vụ đang tính để kiểm soát bộ nhớ.
- [ ] Đo riêng thời gian snap, Dijkstra, quét, xếp hạng, dựng tuyến và tổng xử lý.
- [ ] Ghi số node tới được; chỉ báo cáo số node mở rộng nếu thư viện thực sự cung cấp số liệu đó.
- [ ] Giữ dừng sớm ở trạng thái tắt; không triển khai thêm thuật toán định tuyến khác.
- [ ] Chạy bộ đối chiếu TC-16 với NetworkX trên đồ thị thật.

**Cổng nghiệm thu M3**

- [ ] Cùng tập node kết quả, cùng thứ hạng với bản tham chiếu trên 1.000 request.
- [ ] Score lệch không quá 0,1 giây; tuyến vẫn đạt TC-06.
- [ ] Đường xử lý production không chạy NetworkX.

### M4 — API, cache và rerank

**Đầu ra:** đủ ba API nghiệp vụ, xử lý lỗi và tái sử dụng kết quả đúng.

- [ ] Triển khai tạo kết quả, rerank và cấu hình bản đồ theo mục 3 của kế hoạch.
- [ ] Chuẩn hóa lỗi validation thành HTTP và `error_code` của đặc tả, thay vì để mặc định framework làm thay đổi hợp đồng.
- [ ] Trả đủ A–D trong origins, travel times và routes; geometry dùng GeoJSON `[longitude, latitude]`.
- [ ] Trả graph version, speed profile version, objective weights và timings.
- [ ] Tạo `request_id` khó đoán; cache đủ snaps, offset, bảng khoảng cách và predecessor để rerank không chạy lại Dijkstra.
- [ ] Cache toàn bộ dữ liệu ứng viên cần thiết, không chỉ 5 điểm đã trả.
- [ ] Cài đặt LRU, TTL 15 phút tính từ lần tính gốc và giới hạn bộ nhớ; eviction phải dẫn đến recompute rõ ràng.
- [ ] Khóa cache nguồn chứa phiên bản đồ thị/profile, nguồn snap chính xác và cutoff đã tính; không làm tròn tọa độ để tạo khóa.
- [ ] Giữ offset tiếp cận theo request; kiểm thử hai đầu vào snap cùng điểm nhưng cách đường khác nhau.
- [ ] Rerank khi đổi `phi`, `top_k`, spacing hoặc giảm giới hạn thời gian trong phạm vi đã tính.
- [ ] Trả `RECOMPUTE_REQUIRED` khi yêu cầu vượt cutoff đã cache, cache mất/hết hạn hoặc phiên bản đồ thị thay đổi.
- [ ] Khi di chuyển nguồn, tính lại nguồn thay đổi; chỉ tái sử dụng nguồn khác nếu khóa cache và cutoff vẫn đáp ứng.
- [ ] Trả `status: empty` khi không có ứng viên; chỉ trả ngưỡng tối thiểu dạng số khi có đủ dữ liệu để biết chính xác.
- [ ] Không chạy Dijkstra không cutoff chỉ để tìm gợi ý trong một request thông thường.
- [ ] Có health/readiness; graph thiếu hoặc không hợp lệ thì không nhận request tính toán.
- [ ] Không ghi request body chứa tọa độ chính xác vào log; không lưu cache xuống đĩa.

**Cổng nghiệm thu M4**

- [ ] API contract tests đạt, gồm tất cả mã lỗi.
- [ ] Rerank khớp tính mới với cùng tham số.
- [ ] Có bằng chứng rerank không gọi lại Dijkstra.
- [ ] TC-13 và TC-14 đạt.

### M5 — Frontend và trải nghiệm hoàn chỉnh

**Đầu ra:** toàn bộ user flow hoạt động với backend thật.

- [ ] Hiển thị MapLibre, AOI và attribution OpenStreetMap.
- [ ] Cấu hình style/tile URL theo môi trường; ghi rõ điều khoản, attribution và giới hạn của nguồn tile dùng local.
- [ ] Cho phép chọn người A–D, đặt marker, kéo marker và sửa tọa độ bằng bàn phím.
- [ ] Phân biệt người và điểm gặp bằng nhãn, hình dạng hoặc số thứ tự, không chỉ bằng màu.
- [ ] Kiểm tra đủ 4 vị trí và phạm vi đầu vào trước khi cho tính; backend vẫn là nơi xác thực cuối cùng.
- [ ] Hiển thị vị trí snap, khoảng cách snap và thời gian tiếp cận; vẽ đoạn nối khi khoảng cách trên 30 m.
- [ ] Có slider công bằng với hai nhãn theo đặc tả, mặc định 0,5 và bước 0,1.
- [ ] Có trường giới hạn thời gian với đơn vị rõ ràng và miền giá trị đúng API.
- [ ] Hiển thị tối đa 5 kết quả theo `rank`; không tự tính lại Score hoặc tự sắp xếp.
- [ ] Hiển thị thời gian A–D, xa nhất, nhỏ nhất, chênh lệch, trung bình và điểm nhóm; chuyển giây sang phút một chữ số thập phân.
- [ ] Chọn một kết quả để xem 4 tuyến; có bật/tắt từng tuyến.
- [ ] Hoàn thiện đủ trạng thái `idle`, `ready`, `loading`, `success`, `empty`, `stale`, `error`.
- [ ] Sau khi đổi vị trí, làm mờ kết quả cũ và ghi “chưa cập nhật”; không rerank kết quả theo bộ nguồn đã lỗi thời.
- [ ] Debounce slider 250 ms; dùng rerank khi bộ nguồn chưa đổi.
- [ ] Khi nhận 409, tự gọi lại endpoint tính mới một lần với bộ tham số hiện tại.
- [ ] Hủy hoặc bỏ qua response cũ để thao tác nhanh không ghi đè kết quả mới.
- [ ] Xử lý timeout, API chưa sẵn sàng, snap thất bại và lỗi mạng bằng thông báo cùng thao tác thử lại.
- [ ] Đảm bảo bố cục desktop khoảng 70% bản đồ/30% điều khiển; màn hình hẹp dùng bố cục xếp dọc.
- [ ] Kiểm tra bàn phím, focus, nhãn input, thông báo loading và khả năng đọc màu tuyến.
- [ ] Ghi rõ “thời gian ước lượng”, giới hạn về cấm rẽ và khả năng điểm gặp không phù hợp để dừng xe.
- [ ] Không lưu tọa độ vào localStorage hoặc công cụ analytics.

**Cổng nghiệm thu M5**

- [ ] Hoàn thành user flow mục 9.2 của đặc tả bằng dữ liệu thật.
- [ ] Đổi `phi` cập nhật được kết quả mà không tính lại đường đi.
- [ ] Không xuất hiện kết quả lẫn giữa hai bộ vị trí khi thao tác nhanh.
- [ ] Giao diện hoạt động với các trạng thái lỗi và rỗng.

### M6 — Đóng gói, vận hành local và tài liệu

**Đầu ra:** người khác có thể dựng và kiểm tra MVP theo tài liệu.

- [ ] Tạo Docker image cho backend/frontend và cấu hình Docker Compose.
- [ ] Tách bước dựng dữ liệu offline khỏi bước chạy ứng dụng; runtime không tải OSM.
- [ ] Mount bộ đồ thị theo phiên bản ở chế độ chỉ đọc; kiểm tra metadata và checksum khi khởi động.
- [ ] Cấu hình kết nối frontend/backend và CORS theo môi trường.
- [ ] Có healthcheck; frontend xử lý được thời gian backend đang nạp đồ thị.
- [ ] Kiểm tra giới hạn cache, bộ nhớ và tác vụ đồng thời bằng bài tải thực tế.
- [ ] Đảm bảo log không chứa secret hoặc tọa độ chính xác; có request ID, phiên bản và timings để truy lỗi.
- [ ] Viết hướng dẫn chuẩn bị dữ liệu, chạy local, chạy test, benchmark, thay graph và xử lý lỗi thường gặp.
- [ ] Ghi nguồn OSM, attribution và việc rà soát điều kiện dùng/phân phối dữ liệu dẫn xuất.
- [ ] Ghi cách cấu hình tile provider và lỗi khi nguồn tile không khả dụng.
- [ ] Ghi giới hạn mô hình và các việc thuộc Phase 3–4.
- [ ] Với mỗi task code hoàn thành, tạo journal riêng theo chuẩn journal của dự án, chỉ ghi kết quả thực tế.

**Cổng nghiệm thu M6**

- [ ] Từ một môi trường sạch có Docker và bộ artifact được chỉ định, có thể khởi động ứng dụng theo tài liệu.
- [ ] Smoke test chạy trên AOI nghiệm thu, không dùng kết quả giả thay backend.
- [ ] Có đầy đủ báo cáo kiểm thử và benchmark ở mục 4.

## 3. Hợp đồng API và dữ liệu

### API công khai của MVP

| API | Hành vi bắt buộc |
|---|---|
| `POST /api/v1/meeting-points` | Xác thực, snap, định tuyến, xếp hạng, dựng tuyến và cấp request ID |
| `POST /api/v1/meeting-points/{request_id}/rerank` | Dùng bảng đã cache để xếp hạng lại; trả 409 nếu không đủ dữ liệu |
| `GET /api/v1/map/config` | Trả AOI, phương tiện, giới hạn, mặc định và phiên bản dữ liệu |
| Health/readiness | Phục vụ Docker và kiểm tra graph đã sẵn sàng |

### Validation

- [ ] Đúng 4 origins, ID duy nhất; tọa độ hữu hạn và đúng miền WGS84.
- [ ] Tất cả origins nằm trong hoặc trên biên AOI.
- [ ] Chỉ nhận `travel_mode: car`.
- [ ] `phi` trong `[0, 1]`.
- [ ] `max_travel_seconds` trong `[300, 7200]`.
- [ ] `top_k` trong `[1, 5]`.
- [ ] `min_spacing_meters` trong `[0, 5000]`.
- [ ] Validation tương đương giữa endpoint tạo mới và rerank.

### Dữ liệu và tính nhất quán

- [ ] Phân biệt rõ thời gian mạng gốc, offset tiếp cận gốc và thời gian trả qua API.
- [ ] Thời gian API theo bước 0,1 giây; weights OWA giữ đủ độ chính xác.
- [ ] `travel_times` đã gồm offset tiếp cận.
- [ ] Duration của từng route bằng travel time của đúng người đó.
- [ ] Tổng access và network trả qua API bằng duration theo quy tắc chuẩn hóa.
- [ ] Geometry tuyến bắt đầu tại điểm snap và kết thúc tại điểm gặp; đoạn tiếp cận được hiển thị riêng.
- [ ] Các node, tuyến và metadata trong một response thuộc cùng phiên bản đồ thị/profile.
- [ ] `rank` là thứ tự chuẩn, kể cả khi các score hiển thị bằng nhau.

### Mã lỗi

| Mã | HTTP | Kiểm tra cần có |
|---|---:|---|
| `INVALID_COORDINATES` | 400 | Sai miền, NaN, infinity hoặc kiểu dữ liệu |
| `INVALID_PARAMETERS` | 400 | Số nguồn, ID, phương tiện hoặc tham số sai |
| `OUT_OF_COVERAGE` | 422 | Nguồn ngoài AOI |
| `SNAP_FAILED` | 422 | Không có cạnh hợp lệ trong 150 m |
| `NO_COMMON_REACHABLE_NODE` | 200 | `status: empty`, có gợi ý khi biết |
| `RECOMPUTE_REQUIRED` | 409 | Cache không đáp ứng yêu cầu |
| `GRAPH_UNAVAILABLE` | 503 | Graph chưa sẵn sàng |
| `INTERNAL_ERROR` | 500 | Thông báo an toàn, có request ID |

Response lỗi có `error_code`, `message`, `request_id`. Khi không biết chính xác ngưỡng tối thiểu do cutoff, dùng dạng `"> 3600"` theo tinh thần đặc tả, thay vì trả một giá trị số suy đoán.

## 4. Kiểm thử, hiệu năng và bằng chứng nghiệm thu

### Ma trận TC-01–TC-16

| ID | Nội dung phải kiểm tra | Mốc |
|---|---|---|
| TC-01 | Dijkstra đúng khoảng cách và cạnh song song; hòa thì đúng edge key | M2, M3 |
| TC-02 | Không đi ngược đường một chiều | M2, M3 |
| TC-03 | Score gốc đúng công thức; API làm tròn đúng | M2 |
| TC-04 | Node ngoài cutoff hoặc không tới được bị loại | M2, M3 |
| TC-05 | Bốn nguồn trùng node: hạng 1 tại đó, Score bằng 0 | M2 |
| TC-06 | Tổng trọng số tuyến khớp khoảng cách nội bộ; thời gian API nhất quán | M2–M5 |
| TC-07 | Kết quả tất định; đổi nhãn A–D không đổi tập điểm và Score | M2–M4 |
| TC-08 | 10.000 cặp Pareto × 11 giá trị phi; thêm trường hợp hòa do lượng tử | M2, M3 |
| TC-09 | Chuyển thời gian theo hướng công bằng không làm Score gốc tăng | M2 |
| TC-10 | Bounds, tổng trọng số, phi bằng 0 và tính tịnh tiến | M2 |
| TC-11 | Snap giữa cạnh một chiều/hai chiều; kiểm tra cả tốc độ hai chiều khác nhau | M2, M3 |
| TC-12 | Offset tiếp cận được cộng đúng cho mọi node | M2–M4 |
| TC-13 | 50 request đồng thời không làm thay đổi hash đồ thị dùng chung | M4 |
| TC-14 | Cutoff 900 → 1.800 giây yêu cầu tính lại; kết quả khớp chạy mới | M4, M5 |
| TC-15 | 200 cặp gần biên; ít nhất 198 cặp lệch không quá 1% khi nhân đôi buffer | M1, nghiệm thu |
| TC-16 | 1.000 request đồ thị thật: CSR khớp NetworkX về node, thứ tự và Score | M3, nghiệm thu |

### Kiểm thử bổ sung bắt buộc

- [ ] TC-03 phân biệt score gốc khoảng `10.750 / 11.263 / 11.890` với score API `10.8 / 11.3 / 11.9`.
- [ ] Kiểm thử Pareto với hai vector chỉ khác dưới 0,1 giây và node ID cố tình bất lợi cho điểm tốt hơn.
- [ ] Kiểm thử quanh ranh giới lượng tử, cutoff, khoảng cách snap 150 m và spacing 500 m.
- [ ] Kiểm thử snap đúng đầu mút, đường cong, đoạn hai chiều và cạnh song song khác hình học.
- [ ] Kiểm thử nguồn trùng, nhiều nguồn trên cùng cạnh và nguồn có offset khác nhau.
- [ ] Kiểm thử cache hết hạn, eviction, graph thay phiên bản và rerank sau khi backend restart.
- [ ] Kiểm thử giảm cutoff rồi rerank; kết quả phải khớp tính mới.
- [ ] Kiểm thử không có ứng viên, có ít hơn 5 ứng viên và ứng viên bị loại do spacing.
- [ ] Kiểm thử response đủ 4 origins và đủ 4 routes cho từng kết quả.
- [ ] Kiểm thử UI khi response đến sai thứ tự, mạng lỗi và backend chậm.
- [ ] E2E: đặt nguồn → tính → chọn điểm → xem tuyến → đổi phi → kéo nguồn → tính lại.

### Validation trên dữ liệu thật

- [ ] Chạy TC-15 với cùng nguồn OSM và speed profile; ghi rõ cách lấy mẫu, seed và cách tính sai lệch.
- [ ] Nếu buffer không đạt, tăng buffer, dựng lại và kiểm tra lại; không giảm tiêu chuẩn.
- [ ] Chạy TC-16 trên AOI nghiệm thu, gồm nguồn gần nhau, xa nhau và sát biên.
- [ ] Rà soát thủ công các tuyến gần cầu vượt, nút giao và đường một chiều.
- [ ] Đối chiếu tối thiểu 100 tuyến với dữ liệu thời gian từ dịch vụ độc lập ngoài giờ cao điểm.
- [ ] Báo cáo sai lệch thời gian từng tuyến và sai lệch chênh lệch thời gian giữa các thành viên.
- [ ] Ghi cơ sở giữ hoặc điều chỉnh speed profile; nếu chỉnh thì tăng phiên bản và dựng lại đồ thị.
- [ ] Lưu báo cáo vùng bị loại bởi SCC và tác động đến khả năng snap.
- [ ] Ghi rõ thử nghiệm này không chứng minh tuân thủ cấm rẽ hoặc tính chính xác của ETA thời gian thực.

### Benchmark

Môi trường chuẩn: Docker được cấp **4 vCPU, 8 GiB RAM**. Ghi thêm CPU host, OS, phiên bản thư viện, graph/profile version và cấu hình cache.

- [ ] Đo riêng thời gian nạp graph và dựng spatial index.
- [ ] Warm-up tối thiểu 20 request trước khi đo đường xử lý đã nạp sẵn.
- [ ] Đo ít nhất 1.000 request tính mới; có thể tái sử dụng bộ request TC-16.
- [ ] Đo ít nhất 1.000 lần rerank với nhiều phi và cấu hình kết quả.
- [ ] Bao gồm nguồn gần nhau, xa nhau, gần biên và truy vấn liên tiếp.
- [ ] Đạt P95 xử lý request mới **≤ 5 giây**.
- [ ] Đạt P95 rerank **≤ 300 ms**.
- [ ] Đo ở concurrency 1 cho hai mục tiêu trên; báo cáo riêng tải đồng thời 50 request, không nhập hai kết quả thành một.
- [ ] Ghi thời gian từng bước, tổng xử lý, thời gian HTTP, kích thước response, cache hit/miss và peak memory.
- [ ] Kiểm tra tính cả chi phí dựng tuyến và serialize response; không benchmark riêng scorer rồi coi là toàn API.
- [ ] Nếu không đạt, xác định bước chậm và tối ưu bước đó; chạy lại TC-16 sau thay đổi ảnh hưởng thuật toán.

### Hồ sơ bằng chứng

- [ ] Có báo cáo test tự động, E2E, TC-15, TC-16 và benchmark.
- [ ] Mỗi báo cáo ghi ngày, phiên bản code, môi trường, graph/profile version và seed.
- [ ] Fixture CI là dữ liệu tổng hợp hoặc mẫu cố định; kiểm thử thường ngày không phụ thuộc dịch vụ OSM/ETA đang hoạt động.
- [ ] Phân biệt rõ kiểm tra đã chạy, chưa chạy, thất bại và giới hạn còn lại.

## 5. Checklist hoàn thành MVP và sẵn sàng triển khai

### Nghiệm thu MVP local — tất cả mục dưới đây phải đạt

- [ ] **FR-01, FR-02:** đặt và chỉnh đúng 4 vị trí trong AOI trên bản đồ tương tác.
- [ ] **FR-03:** snap đúng, có offset tiếp cận và chỉ báo trên giao diện.
- [ ] **FR-04:** định tuyến đúng chiều, cutoff đúng, không sửa đồ thị dùng chung.
- [ ] **FR-05:** OWA đúng, lượng tử đúng và thứ hạng bảo toàn Pareto theo bổ sung đã chốt.
- [ ] **FR-06:** tối đa 5 điểm; cấu hình mặc định cách nhau ít nhất 500 m; không tự nới spacing.
- [ ] **FR-07:** mỗi điểm có đủ 4 tuyến từ hình học cạnh, khớp thời gian nội bộ.
- [ ] **FR-08:** hiển thị đầy đủ kết quả, chỉ số và nhãn thời gian ước lượng.
- [ ] **FR-09:** đổi phi không chạy lại Dijkstra; tăng vượt cutoff đã tính yêu cầu recompute.
- [ ] **NFR-01:** có benchmark trên AOI đầy đủ và đạt hai mục tiêu P95.
- [ ] **NFR-02:** TC-01–TC-12, TC-15 và TC-16 đạt; metadata có thống kê thời gian cạnh.
- [ ] **NFR-03:** TC-13, TC-14 đạt; lỗi, empty, stale và response đến muộn được xử lý.
- [ ] **NFR-04:** không yêu cầu tài khoản, không lưu tọa độ lâu dài, cache giới hạn và log bảo vệ vị trí.
- [ ] **NFR-05:** có attribution và tài liệu nguồn dữ liệu/tile cùng điều kiện sử dụng tương ứng.
- [ ] Chạy được từ môi trường sạch bằng Docker và artifact có phiên bản.
- [ ] Có hướng dẫn vận hành local, tái tạo dữ liệu và thay phiên bản đồ thị.
- [ ] Có báo cáo kiểm thử, benchmark và danh sách giới hạn đã biết.
- [ ] Rà soát từng acceptance criterion ở mục 15 của đặc tả; không còn mục bắt buộc chưa có bằng chứng.

### Checklist triển khai công khai — thực hiện sau MVP local

Các mục này chưa được tính là đã thực hiện trong kế hoạch local.

- [ ] Chốt máy chủ, domain, tile provider và quyền sử dụng phù hợp lưu lượng dự kiến.
- [ ] Cấu hình HTTPS, reverse proxy, CORS, timeout, giới hạn request và xử lý quá tải.
- [ ] Bắt đầu với một instance/worker để cache request hoạt động nhất quán.
- [ ] Cấu hình health/readiness, giám sát lỗi, latency, bộ nhớ và cache eviction.
- [ ] Giữ graph chỉ đọc; phát hành code, AOI, graph và speed profile theo bộ phiên bản tương thích.
- [ ] Có quy trình rollback; client xử lý được cache mất sau deploy.
- [ ] Kiểm tra log, quyền truy cập và secret trên môi trường triển khai.
- [ ] Chạy smoke test công khai, kiểm tra attribution và đo lại hiệu năng trên máy chủ thật.

### Giới hạn còn lại sau MVP

MVP cung cấp gợi ý điểm gặp theo mô hình thời gian tĩnh. Chất lượng định tuyến còn phụ thuộc dữ liệu OSM, speed profile, snapping và việc chưa xét cấm rẽ/chi phí rẽ. Việc dùng như công cụ chỉ đường cần hoàn thành phần Routing Quality của Phase 3.

M0 hoàn thành local. Người phát triển xác nhận frontend install, audit (0 vulnerabilities), lint, typecheck, production build và trang chủ hiển thị với Next.js 16.4.5. Backend Ruff và 26 pytest đạt trên Python 3.12.13; có một cảnh báo deprecation TestClient/httpx. Smoke test HTTP backend đạt: health 200, ready/map config 503 đúng kỳ vọng khi chưa có graph. Git và hai lockfile đã tồn tại; chưa xác minh remote CI hoặc thực hiện commit. M1 đã có AOI thử nghiệm, snapshot OSM thật và artifact chuẩn hóa hình học EPSG:32648 (Ruff và 94 test đạt); các phần M1 còn lại, M2–M6 và toàn bộ nghiệm thu MVP vẫn để mở.
