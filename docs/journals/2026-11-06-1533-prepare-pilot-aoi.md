# Chuẩn bị AOI thử nghiệm và buffer định tuyến

**Date:** 2026-11-06 15:33  
**Status:** Partially Completed

## Summary

Đã viết phần chuẩn bị AOI offline cho bước đầu M1: nguồn polygon thử nghiệm,
kiểm tra hình học và buffer định tuyến 3 km. Chưa chạy script hoặc kiểm thử;
người phát triển sẽ tự thực hiện các lệnh.

## Changes Made

- Thêm polygon phiên bản `hanoi-pilot-v1`, bounds `[105.84, 21.02, 105.86, 21.04]`.
- Viết bộ đọc Polygon/Feature, từ chối vòng chưa đóng, tọa độ sai và topology lỗi.
- Dùng `covers` để chấp nhận điểm trên biên; phần trong lỗ polygon bị loại.
- Chiếu sang EPSG:32648, buffer theo mét, xuất GeoJSON WGS84 và metadata hash nguồn.
- Thêm CLI, cấu hình đường dẫn và test offline cho hình học, khoảng cách, artifact và lỗi.

## Files Affected

- `backend/app/config/areas/hanoi-pilot-v1.geojson` — nguồn vùng thử nghiệm.
- `backend/app/services/area.py` — validation, coverage và buffer.
- `backend/scripts/prepare_aoi.py` — xuất AOI, routing area và metadata.
- `backend/app/config/settings.py`, `.env.example` — cấu hình đường dẫn.
- `backend/tests/test_area.py` — regression tests không dùng dịch vụ ngoài.

## Technical Decisions

- Phân biệt AOI đầu vào với vùng định tuyến; buffer không mở rộng phạm vi hỗ trợ.
- Dùng `always_xy=True`; hình học API giữ thứ tự `[lon, lat]`.
- Buffer dùng 64 đoạn mỗi góc phần tư để hạn chế sai số xấp xỉ cung tròn.
- Nguồn nhỏ nằm trong config được version; artifact sinh ra nằm trong data bị ignore.

## Verification

- **Tests:** đã viết, chưa chạy.
- **Build/Lint/Typecheck:** chưa chạy sau thay đổi.
- **Manual Verification:** rà soát nội dung code; chưa sinh hoặc kiểm tra artifact runtime.

## Known Issues / Limitations

Polygon là vùng kỹ thuật thử nghiệm, chưa phải AOI toàn nội đô đã được rà soát.
Chưa có OSM hoặc đồ thị; readiness/API vẫn trả 503. Lỗi ghi có thể để lại bộ
artifact thiếu file; tài liệu yêu cầu chỉ sử dụng khi xuất thành công đủ ba file.

## Next Steps

Người phát triển chạy Ruff, pytest và CLI theo README; rà soát output trước khi nghiệm thu.
