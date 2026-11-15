# Lọc ứng viên và xếp hạng OWA tham chiếu

**Date:** 2026-11-15 14:06  
**Status:** Completed

## Summary

Bổ sung bước lọc và xếp hạng toàn bộ ứng viên từ bảng định tuyến đã có. Hàm
mục tiêu tổng quát cho K nguồn, dùng khóa phá hòa bảo toàn Pareto sau lượng tử.

## Changes Made

- Tách scorer OWA gốc, trọng số dương và lượng tử half-even dùng chung.
- Lọc theo cờ M1, khả năng tới được và thời gian tổng gốc trước lượng tử;
  giữ node chia cạnh nhưng không đưa nguồn overlay vào tập ứng viên.
- Giữ cả vector gốc và đã lượng tử. Khóa sắp dùng vector gốc giảm dần trước
  node ID; trả toàn bộ danh sách cho bước spacing tiếp theo.
- Từ chối giới hạn vượt cutoff đã tính; đổi phi hoặc giảm giới hạn dùng lại
  bảng hiện có, không chạy Dijkstra hoặc sửa dữ liệu đầu vào.

## Files Affected

- `backend/app/services/objective.py` — công thức, lượng tử và dữ liệu điểm.
- `backend/app/services/meeting_optimizer.py` — lọc, kiểm tra phạm vi và sắp xếp.
- `backend/tests/test_objective.py`, `backend/tests/test_meeting_optimizer.py`
  — kiểm thử toán học và kết quả đã lượng tử riêng biệt.

## Technical Decisions

- Dùng float64, `math.fsum` và weights tính một lần mỗi lượt xếp hạng.
- Max/min, chênh lệch, trung bình lấy từ thời gian đã lượng tử theo pseudocode;
  raw times chỉ quyết định cutoff và phá hòa, không thay công thức score.

## Verification

- **Tests:** 369 test backend đạt, không bỏ qua; 554 cảnh báo deprecation.
  Có 10.000 cặp Pareto qua 11 giá trị phi, fairness, bounds và tính tịnh tiến.
- **Build/Lint/Typecheck:** Ruff và kiểm tra whitespace các file đã sửa của
  task đạt. Kiểm tra toàn working tree còn báo dòng trống EOF ở `README.md`
  từ thay đổi có sẵn; giữ nguyên. Không chạy frontend vì không thay đổi.
- **Manual Verification:** Bundle M1 cho 96.410 ứng viên tại phi 0/0,5/1;
  điểm đầu không bị ứng viên nào trội hơn. Hash routing/graph trước và sau
  xếp hạng không đổi. Không tải OSM.

## Known Issues / Limitations

- Chưa lọc spacing/top_k, gán rank API, dựng tuyến hoặc tích hợp HTTP.
  Chưa nghiệm thu toàn bộ M2; không thêm dependency hoặc đổi `.env`.

## Next Steps

- Lọc đa dạng không gian tham lam, sau đó dựng tuyến từ predecessor đã lưu.
