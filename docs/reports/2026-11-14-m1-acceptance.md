# Nghiệm thu M1 — dữ liệu đồ thị offline

Ngày kiểm tra: **2026-11-14**, môi trường local. Kết luận: **M1 đạt trên AOI kỹ
thuật đã được chủ dự án duyệt trong cuộc trao đổi của task**. M2–M6 chưa nghiệm thu.

Bằng chứng có phiên bản code, checksum triển khai/artifact, môi trường, metadata
và đủ 200 cặp TC-15 nằm trong [báo cáo JSON](2026-11-14-m1-acceptance.json).
HEAD gốc `6a585abc2ee3f491f7e60d8e57c9b66812b70232`; thay đổi của task chưa commit.

## Phạm vi và dữ liệu nguồn

- AOI `hanoi-ring3-v1`: **304,5586 km²**, polygon kỹ thuật xấp xỉ phạm vi Vành đai 3.
  Chủ dự án đã duyệt dùng cho M1; đây không phải ranh giới hành chính hoặc tim
  đường được đo đạc. Thuộc tính yêu cầu duyệt trong polygon nguồn được giữ để
  truy vết; quyết định duyệt được ghi trong báo cáo này.
- Hướng tuyến tham chiếu từ [Viện Khoa học và Công nghệ GTVT](https://itst.gov.vn/vi/news/tin-tuc/4787-4787.html).
  Tọa độ polygon là lựa chọn kỹ thuật của dự án, không lấy từ hồ sơ đo đạc đó.
- Chấp nhận điểm trên biên bằng `covers`; khoảng cách và buffer dùng EPSG:32648.
  Quy tắc UI được khóa trong bổ sung hợp đồng M0; tích hợp frontend thuộc M5.
- Một snapshot OSM duy nhất tại `2026-11-06T09:28:34Z`, tải offline ngày 2026-11-14,
  có 217.991 node/430.425 cạnh. Hai bản được cắt theo node từ snapshot này;
  cùng bộ lọc `drive`, giữ chiều đi/cạnh song song và profile `car-v1`.

## Bộ artifact và kiểm tra

| Nội dung | Buffer 3.000 m | Buffer 6.000 m |
|---|---:|---:|
| Node sau tiền xử lý | 149.213 | 213.143 |
| Cạnh/cung CSR | 290.952 | 422.978 |
| Ứng viên | 96.410 | 96.414 |
| Thời gian cạnh lớn nhất | 59,9315 s | 59,9315 s |
| Khoảng cách đối chiếu NetworkX | 2.984.260 | 4.262.860 |
| Sai số khoảng cách lớn nhất | 0 s | 0 s |

Bundle chính: `backend/data/builds/hanoi-ring3-car-v1-3000-v1/validated/`.
Bản 6 km dùng đường dẫn tương ứng `hanoi-ring3-car-v1-6000-v1/validated/`.

Cả hai đạt kiểm tra checksum, nạp lại offline, SCC, đơn vị/trọng số, cờ ứng viên,
AOI, metadata mục 10.4, toàn bộ ánh xạ CSR/geometry và ngưỡng cạnh 60 giây.
Mỗi bản dựng 200 tuyến mẫu từ predecessor SciPy rồi kiểm tra cạnh song song và
tổng thời gian theo sai số spec. Bản chính có sai số tổng tuyến lớn nhất
`3,1833e-12 s`; P50/P99/max thời gian cạnh là **3,7454/33,7883/59,9315 s**.
Trên graph cuối có 75 cạnh dùng default speed và 64 cạnh bị maxspeed giới hạn.

## TC-15

**Đạt 200/200 cặp**, yêu cầu ít nhất 198/200. Sai lệch tương đối lớn nhất **0%**.

Seed `20261114`; lấy đều không hoàn lại 200 cặp có hướng từ 20.436 node OSM gốc
trong AOI, cách biên không quá 1 km. Loại cặp nguồn trùng đích và node sinh khi
chia cạnh. Tính `abs(t_3km - t_6km) / t_6km` từ Dijkstra có hướng, không lượng tử.
Node thiếu hoặc cặp không tới được ở bản đối chiếu tính là thất bại, không lấy
mẫu thay thế. Không cần tăng buffer mặc định.

## Rà soát SCC và giới hạn snapping

Graph 3 km giữ SCC lớn nhất trong 1.497 SCC; loại 3.817 node/5.779 cạnh trên toàn
routing area. Trong AOI có 1.797 node và 2.934 feature cạnh bị loại.

[Bản đồ chủ dự án duyệt](../../backend/data/reviews/hanoi-ring3-v1-3000.svg)
và [bản đồ kèm thống kê](../../backend/data/reviews/hanoi-ring3-v1-3000-v2.svg)
không dùng tile: xanh là biên AOI, đỏ là phần bị loại. SVG đã được kiểm tra cấu
trúc XML; việc duyệt phạm vi là quyết định của chủ dự án, không phải kết luận
về độ chính xác địa chính.

STRtree trên đường được giữ cho thấy **404/1.797 node bị loại cách đường hơn
150 m**, xa nhất **599,19 m**. Có 774/2.934 trung điểm feature cạnh cũng quá
150 m; đây chỉ là mẫu trung điểm, không phải kiểm tra mọi điểm trên cạnh.
Một số đầu vào trong AOI sẽ có thể trả `SNAP_FAILED`. Không mở rộng snap radius,
thêm chiều đi hoặc giữ các SCC rời để che giới hạn này.

## Kiểm tra mã và bước tiếp theo

- `backend/.venv/bin/python -m pytest backend/tests -q --disable-warnings`:
  **306 đạt, không bỏ qua, 356 cảnh báo deprecation** từ Shapely/TestClient.
- `backend/.venv/bin/ruff check backend` và `git diff --check`: đạt.
- Frontend lint/typecheck/build không chạy vì không sửa frontend.
- Chưa chạy TC-16, benchmark API, hiệu chỉnh 100 tuyến hoặc triển khai runtime;
  chúng không được tính là hoàn thành bởi báo cáo M1.

Tiếp theo là M2: pipeline tham chiếu snapping → overlay → Dijkstra → OWA →
spacing → dựng tuyến, kiểm tra TC-01–TC-12. Bảng tốc độ vẫn là giả định tĩnh;
chưa xử lý cấm rẽ/chi phí rẽ hoặc bảo đảm điểm gặp thích hợp để dừng xe.

Artifact lớn nằm trong thư mục dữ liệu được Git bỏ qua. Cách tái tạo, lệnh tải
offline và kiểm tra buffer có trong [hướng dẫn dữ liệu](../../backend/data/README.md#aoi-vành-đai-3-và-nghiệm-thu-m1).
Không thay `.env`, polygon pilot hoặc artifact lịch sử.
