# Xác thực AOI và snapping tham chiếu M2

**Date:** 2026-11-14 16:41  
**Status:** Completed

## Summary

Bổ sung loader bundle M1 và snapping offline cho bốn nguồn. Kết quả chứa đủ
thông tin nguồn để triển khai overlay và Dijkstra ở task tiếp theo.

## Changes Made

- Nạp graph NetworkX sau khi kiểm tra checksum, phiên bản, CRS, trọng số, SCC
  và mapping cạnh ngược; khóa cấu trúc graph, không sửa artifact.
- Kiểm tra AOI cho toàn bộ nguồn trước snapping. Dựng STRtree trên mọi đường
  SCC, gộp cặp ngược trùng geometry, giữ riêng cạnh song song khác hình học.
- Phá hòa bằng ID cạnh; tính điểm chiếu, theta, khoảng cách và thời gian tiếp
  cận chưa lượng tử. Trả mã lỗi an toàn, không chứa tọa độ.

## Files Affected

- `backend/app/services/graph_loader.py` — nạp graph tham chiếu đã validation.
- `backend/app/services/coordinate_snapper.py` — index, kết quả bất biến và lỗi.
- `backend/tests/test_graph_loader.py`, `backend/tests/test_coordinate_snapper.py`
  — kiểm thử dữ liệu hỏng, hình học, ngưỡng, tính tất định và bất biến graph.

## Technical Decisions

- Chỉ gộp cặp ngược đã xác nhận và đảo tọa độ chính xác; không suy luận từ đầu
  mút hoặc dịch geometry để ghép đường.
- Dung sai đầu mút 1e-7 m xử lý roundtrip WGS84; chỉ chuẩn hóa nếu vẫn trong
  bán kính snap. Graph freeze chỉ bảo vệ cấu trúc, không đóng băng thuộc tính.

## Verification

- **Tests:** 327 test backend đạt, không bỏ qua; 554 cảnh báo deprecation.
- **Build/Lint/Typecheck:** Ruff đạt. Frontend không chạy vì không thay đổi.
- **Manual Verification:** Bundle M1 thật tạo 162.794 mục index; bốn nguồn tổng
  hợp khớp tìm kiếm vét cạn và tái sử dụng đúng node đầu mút. Không tải mạng.

## Known Issues / Limitations

- Chưa tạo overlay, chạy Dijkstra hoặc tích hợp HTTP; chưa nghiệm thu toàn bộ
  TC-11/TC-12 hay toàn mốc M2. Không thêm dependency hoặc thay cấu hình môi trường.

## Next Steps

- Tạo overlay riêng cho request và chạy Dijkstra với cutoff theo access gốc.
