# Lọc đa dạng không gian và dựng tuyến tham chiếu

**Date:** 2026-11-15 14:39  
**Status:** Completed

## Summary

Bổ sung chọn điểm tham lam và dựng tuyến từ cây predecessor đã lưu, hoàn
thiện đầu ra từng điểm gặp của prototype NetworkX mà không chạy lại Dijkstra.

## Changes Made

- Chọn tối đa top_k theo thứ tự xếp hạng, đo spacing trên EPSG:32648;
  không nới khoảng cách khi thiếu điểm.
- Khôi phục đúng edge key và đoạn cạnh nguồn tạm; ghép geometry thực,
  từ chối cây bị đứt/vòng lặp, hình học không liên tục hoặc tổng thời gian sai.
- Trả MeetingResult có rank và tuyến từng nguồn. Khoảng cách chỉ gồm mạng
  đường; tuyến 0 mét dùng hai tọa độ trùng nhau, GeoJSON theo thứ tự lon/lat.

## Files Affected

- `backend/app/services/meeting_optimizer.py` — chọn điểm và tạo kết quả.
- `backend/app/services/route_builder.py` — dựng tuyến và kiểm tra nhất quán.
- `backend/tests/test_route_builder.py` — 24 ca hồi quy bổ sung.

## Technical Decisions

- Chỉ dựng geometry sau khi chọn điểm; giữ toàn bộ bảng xếp hạng để tái sử dụng.
- Kiểm tra tổng trọng số bằng số thực gốc. Thời gian API tính theo tick
  decisecond; network là phần dư của duration trừ access theo bổ sung M0.

## Verification

- **Tests:** 393 test backend đạt, không bỏ qua; 554 cảnh báo deprecation.
- **Build/Lint/Typecheck:** Ruff và `git diff --check` đạt; không chạy frontend.
- **Manual Verification:** Bundle `hanoi-ring3-car-v1-3000-v1`, bốn nguồn tổng
  hợp, phi 0/0,5/1: mỗi lượt 96.410 ứng viên, 5 điểm và 20 tuyến. Spacing nhỏ
  nhất lần lượt 516,976 / 508,686 / 508,774 m; serialize model đạt.
  Chặn lời gọi Dijkstra trong bước xếp hạng/dựng tuyến; hash dữ liệu graph và
  bảng định tuyến trước/sau khớp. Phép hash toàn object ban đầu báo khác do cache
  view của NetworkX; kiểm tra lại trên cấu trúc và thuộc tính graph đạt.

## Known Issues / Limitations

- Chưa tích hợp HTTP, cache hoặc CSR production; chưa nghiệm thu toàn bộ M2.
  Không thêm dependency, tải OSM hoặc thay cấu hình môi trường.

## Next Steps

- Rà soát đầy đủ TC-01–TC-12 và các tiêu chí để nghiệm thu M2.
