# Xuất CSR và ánh xạ đồ thị

**Date:** 2026-11-11 09:42  
**Status:** Completed

## Summary

Bổ sung bước xuất CSR có hướng từ graph đã gắn cờ ứng viên. Bundle có phiên bản chứa graph tham chiếu, ma trận trọng số, ánh xạ node/cung, geometry và dữ liệu nguồn để định tuyến, snapping và dựng tuyến ở các mốc sau.

## Changes Made

- Chọn cạnh theo `(travel_time, edge_key)` cho mỗi cặp node có hướng. Tạo CSR trực tiếp từ data, indices và indptr.
- Sắp node ID và ID cạnh tất định. Lưu cờ ứng viên, tọa độ, ánh xạ offset CSR sang cạnh và geometry của toàn bộ cạnh.
- CLI kiểm tra checksum đầu vào, lưu/nạp lại và khoảng cách với NetworkX trước khi công bố bundle trong thư mục mới.

## Files Affected

- `backend/app/services/graph_csr.py` — dựng CSR và các mảng ánh xạ.
- `backend/scripts/prepare_graph_csr.py` — xuất và kiểm chứng bundle.
- `backend/tests/test_graph_csr.py` — kiểm thử hướng đi, cạnh song song, predecessor, geometry và lỗi đầu vào.
- `backend/data/README.md` — mô tả hợp đồng mảng và cách tra ánh xạ.

## Technical Decisions

- Geometry dùng tọa độ EPSG:32648 và offsets theo thứ tự cạnh để dựng STRtree. Giữ cả cạnh song song ngoài CSR để phục vụ snapping.
- ID node theo chỉ số CSR cung cấp ánh xạ hai chiều qua phép enumerate, gồm cả ID âm sau chia cạnh.

## Verification

- **Tests:** 276 test backend đạt, có 58 cảnh báo deprecation, không bỏ qua test.
- **Build/Lint/Typecheck:** Ruff và `git diff --check` đạt. Frontend build/typecheck không chạy trong task backend này.
- **Manual Verification:** Xuất `backend/data/csr/hanoi-pilot-car-v1-csr-v1/`. Đối chiếu 404.420 khoảng cách với NetworkX, sai số lớn nhất 0 giây. Kiểm tra độc lập toàn bộ cung, geometry, checksum, graph nguồn và dựng STRtree đạt.

## Known Issues / Limitations

- Dữ liệu thật hiện tại có một cạnh cho mỗi cặp node có hướng. Quy tắc cạnh song song được kiểm tra bằng graph tổng hợp.
- Nghiệm thu AOI toàn nội đô, TC-15, TC-16 và tích hợp runtime còn mở.

## Next Steps

- Hoàn thiện báo cáo validation và metadata M1, rà soát AOI và phần bị SCC loại.
