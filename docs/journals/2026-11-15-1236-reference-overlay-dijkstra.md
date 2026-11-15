# Overlay request và Dijkstra tham chiếu M2

**Date:** 2026-11-15 12:36  
**Status:** Completed

## Summary

Bổ sung định tuyến tham chiếu từ kết quả snapping: mỗi nguồn có bảng khoảng
cách mạng và predecessor đủ edge key, dùng cho scorer và dựng tuyến tiếp theo.

## Changes Made

- Tạo graph riêng cho request, giữ cạnh gốc và thêm nguồn tạm chỉ có cạnh ra.
  Hai chiều dùng trọng số riêng; nhiều nguồn cùng cạnh hoạt động độc lập.
- Cắt geometry phần cạnh theo chiều đi và lưu cạnh gốc để truy vết; đầu mút
  dùng node hiện hữu. Dữ liệu snap không nhất quán bị từ chối.
- Chạy NetworkX Dijkstra với cutoff trừ access gốc, giữ khoảng cách và một
  predecessor cho từng node bền vững, không lưu toàn bộ tuyến tới mọi node.

## Files Affected

- `backend/app/services/request_overlay.py` — graph riêng và các đoạn xuất phát.
- `backend/app/services/shortest_path.py` — Dijkstra và nối pipeline snapping.
- `backend/tests/test_reference_routing.py` — 14 ca kiểm thử định tuyến/overlay.

## Technical Decisions

- Sao chép graph chỉ dùng cho bản tham chiếu offline; không tối ưu production
  trước M3. Dictionary thuộc tính riêng, geometry gốc không bị sửa.
- Chèn cạnh tất định, chọn cạnh song song theo thời gian rồi key. Predecessor
  cùng thời gian dùng phần tử đầu tiên NetworkX trả về.
- Thời gian mạng, access và cutoff giữ số thực gốc; nguồn tạm không xuất hiện
  trong bảng ứng viên bền vững.

## Verification

- **Tests:** 341 test backend đạt, không bỏ qua; 554 cảnh báo deprecation.
- **Build/Lint/Typecheck:** Ruff đạt; frontend không chạy vì không thay đổi.
- **Manual Verification:** Bốn nguồn giữa cạnh trên bundle M1, mỗi nguồn tới
  149.213 node, khớp oracle NetworkX trên graph gốc cộng đoạn xuất phát. Hash
  graph chung trước/sau bằng nhau. Test kiểm tra tổng thời gian predecessor,
  cutoff, self-loop, geometry cong, lỗi và thứ tự nguồn.

## Known Issues / Limitations

- Graph riêng tốn thêm bộ nhớ; không coi là đường production hoặc benchmark API.
- Chưa lọc/chấm ứng viên, dựng tuyến API, cache hoặc tích hợp HTTP; chưa nghiệm
  thu toàn bộ M2. Không thêm dependency, tải OSM hoặc thay `.env`.

## Next Steps

- Lọc ứng viên theo thời gian gốc và triển khai OWA, lượng tử, xếp hạng.
