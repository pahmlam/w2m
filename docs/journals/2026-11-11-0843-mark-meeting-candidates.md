# Gắn cờ node ứng viên điểm gặp

**Date:** 2026-11-11 08:43  
**Status:** Completed

## Summary

Bổ sung bước offline xác định node đủ điều kiện làm điểm gặp từ graph đã chia cạnh. Cờ ứng viên phản ánh phạm vi AOI và danh sách loại trừ tùy chọn.

## Changes Made

- Ghi `in_aoi` cho node trong hoặc trên biên AOI và `is_candidate` cho node đủ điều kiện, kể cả node sinh từ chia cạnh.
- Đọc danh sách ID loại trừ từ JSON và từ chối ID sai kiểu, trùng hoặc không có trong graph.
- Xuất GraphML cùng ánh xạ, profile, AOI, checksum và thống kê ứng viên. Kiểm tra graph sau khi nạp lại trước khi xuất artifact.

## Files Affected

- `backend/scripts/prepare_graph_candidates.py` — CLI gắn cờ và xuất artifact.
- `backend/scripts/prepare_graph_split.py` — dùng chung cấu hình kiểu dữ liệu GraphML.
- `backend/tests/test_graph_split.py` — kiểm tra điều kiện ứng viên, loại trừ và lưu/nạp graph.

## Technical Decisions

- Tách phạm vi địa lý khỏi điều kiện làm điểm gặp để graph vẫn định tuyến qua node bị loại trừ.

## Verification

- **Tests:** 261 test backend đạt, với 58 cảnh báo deprecation.
- **Build/Lint/Typecheck:** Ruff đạt. Lượt này chỉ chạy kiểm tra backend.
- **Manual Verification:** Chạy CLI trên AOI thử nghiệm với danh sách rỗng. Đối chiếu 2.504 ứng viên với polygon và xác nhận graph sau khi bỏ hai cờ khớp graph nguồn.

## Known Issues / Limitations

- Chưa có danh sách loại trừ thực địa cho AOI thử nghiệm.

## Next Steps

- Xuất CSR cùng ánh xạ node và cạnh từ artifact đã gắn cờ.
