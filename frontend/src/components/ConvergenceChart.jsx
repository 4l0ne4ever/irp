import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

export function ConvergenceChart({ data, configuredGenerations }) {
  if (!data.length) return <p style={{ color: "#888" }}>No convergence data yet</p>;
  const lastGen = data.length ? data[data.length - 1]?.generation : null;
  return (
    <div style={{ width: "100%" }}>
      <div style={{ width: "100%", height: 280 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="generation" />
            <YAxis />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="best_fitness" name="Best" stroke="#c62828" dot={false} />
            <Line type="monotone" dataKey="avg_fitness" name="Average" stroke="#1565c0" dot={false} strokeDasharray="4 4" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p style={{ fontSize: 12, color: "#555", marginTop: 10, lineHeight: 1.45 }}>
        Trục ngang = chỉ số thế hệ (0, 1, 2, …). Đường cong có thể kết thúc trước mục tiêu{" "}
        <strong>{configuredGenerations != null ? configuredGenerations : "—"}</strong> thế hệ: GA dừng sớm khi{" "}
        <strong>không cải thiện chi phí</strong> đủ lâu (hội tụ), hoặc khi hết <strong>Time limit</strong> — đó là hành vi
        bình thường, không phải treo UI.         Điểm cuối trên đồ thị: thế hệ <strong>{lastGen != null ? lastGen : "—"}</strong>. Nếu sau đó có thông báo vàng “Solver vẫn đang chạy” mà đường cong không đổi — đó là bước hậu xử lý / ghi file / tạo bản đồ, không phải lỗi đồ thị.
      </p>
    </div>
  );
}
