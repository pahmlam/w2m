# Hoàn thiện pipeline và nghiệm thu dữ liệu M1

**Date:** 2026-11-14 16:09  
**Status:** Completed

## Summary

Hoàn thiện đường dựng đồ thị offline trên AOI kỹ thuật Vành đai 3 được chủ dự
án duyệt. Bộ dữ liệu 3 km đạt validation và TC-15, đủ đầu vào cho prototype M2.

## Changes Made

- Thêm polygon kỹ thuật 304,56 km² và CLI `build_graph` gọi các bước tiền xử lý
  hiện có, từ snapshot đến bundle CSR đã validation.
- Thêm TC-15 offline: 200 cặp có hướng gần biên, seed cố định, so buffer 3/6 km
  từ cùng snapshot. Cặp không đối chiếu được tính thất bại; CLI giữ báo cáo lỗi.
- Thêm SVG rà soát SCC và thống kê khoảng cách từ phần bị loại đến đường giữ
  lại bằng STRtree. Tận dụng script validation có sẵn trong working tree.

## Files Affected

- `backend/scripts/build_graph.py` — điều phối các bước, kiểm tra vùng phủ và
  provenance snapshot; không tải mạng.
- `backend/scripts/validate_buffer.py` — kiểm tra TC-15.
- `backend/scripts/render_graph_review.py` — xuất SVG và thống kê SCC.
- `backend/app/config/areas/hanoi-ring3-v1.geojson` — AOI kỹ thuật.
- `backend/tests/test_build_graph.py`, `test_validate_buffer.py`,
  `test_render_graph_review.py` — 17 ca kiểm thử bổ sung.

## Technical Decisions

- Tải một snapshot mở rộng, cắt theo node cho từng buffer, giữ hướng và cạnh
  song song. Manifest ghi checksum nguồn; không sửa artifact đầu vào.
- Giữ các giai đoạn đã hoàn thành nếu bước sau thất bại để kiểm tra nguyên
  nhân; đích build mới không ghi đè thư mục đã tồn tại.

## Verification

- **Tests:** 306 test backend đạt, không bỏ qua; 356 cảnh báo deprecation.
- **Build/Lint/Typecheck:** Ruff và `git diff --check` đạt; frontend không chạy.
- **Manual Verification:** Hai bundle nạp lại offline và validation đạt.
  Bản chính có 149.213 node/290.952 cạnh, max 59,9315 giây; 2.984.260 khoảng cách
  khớp NetworkX. TC-15 đạt 200/200, sai lệch lớn nhất 0%. Chủ dự án duyệt AOI.

## Known Issues / Limitations

- 404 node bị SCC loại trong AOI cách đường giữ lại hơn 150 m; có thể gây
  `SNAP_FAILED`. Polygon là xấp xỉ kỹ thuật; `car-v1` chưa hiệu chỉnh.
- Runtime, TC-16 và benchmark API chưa triển khai/nghiệm thu.

## Next Steps

- Thực hiện pipeline tham chiếu NetworkX và TC-01–TC-12 của M2.
