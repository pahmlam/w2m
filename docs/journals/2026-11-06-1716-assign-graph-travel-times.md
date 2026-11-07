# Gán tốc độ và thời gian cạnh offline

**Date:** 2026-11-06 17:16  
**Status:** Partially Completed

## Summary

Đã viết bước gán trọng số M1 từ artifact hình học EPSG:32648. Chưa xác minh thực thi; người phát triển yêu cầu nhận lệnh để tự chạy.

## Changes Made

- Đọc profile car-v1, kiểm tra đơn vị, phiên bản và tốc độ hữu hạn dương.
- Tra highway dạng đơn/danh sách, dùng default khi thiếu loại.
- Parse maxspeed km/h, mph, danh sách và dấu chấm phẩy; bỏ giá trị không hợp lệ.
- Tính tốc độ có cận trên và thời gian giây trên bản sao đồ thị.
- CLI kiểm tra checksum, lưu profile, GraphML và metadata thống kê; chỉ công bố sau kiểm tra nạp lại.
- Thêm test cho parser, profile, cạnh lỗi, tính bất biến và CLI offline.

## Files Affected

- `backend/app/services/graph_weights.py` — profile, parser và trọng số.
- `backend/scripts/prepare_graph_weights.py` — xuất artifact weighted.
- `backend/tests/test_graph_weights.py` — regression test.
- `backend/data/README.md`, `docs/plans/W2M-MVP-Plan.md` — lệnh chạy và trạng thái chờ xác minh.

## Technical Decisions

- Dùng mph × 1,609 theo spec; maxspeed chỉ làm cận trên.
- Giữ travel_time làm alias của travel_time_seconds.
- Đếm default một lần mỗi cạnh nếu bất kỳ mục highway phải dùng fallback.
- Dừng khi cạnh lỗi; không tự loại/sửa cạnh.

## Verification

- **Tests:** Chưa chạy; đã cung cấp lệnh pytest với extra data để chạy cả roundtrip OSMnx.
- **Build/Lint/Typecheck:** Chưa chạy; đã cung cấp lệnh Ruff. Không thay frontend.
- **Manual Verification:** Đã đọc và rà mã nguồn; chưa chạy CLI hoặc tạo artifact weighted.

## Known Issues / Limitations

- Chưa có kết quả kiểm thử và validation trên dữ liệu thật.
- Chưa lọc SCC, chia cạnh hoặc xuất CSR; car-v1 chưa hiệu chỉnh.

## Next Steps

- Người phát triển chạy Ruff, pytest và CLI; đọc metadata trước khi tick nghiệm thu.
- Sau xác minh, tiếp tục lọc SCC lớn nhất.
