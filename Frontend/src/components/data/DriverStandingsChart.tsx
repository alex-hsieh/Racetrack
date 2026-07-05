import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import './DriverStandingsChart.css';
import { getTeamColor } from '../../utils/teamColors';

export interface DriverStanding {
  position: number;
  name: string;
  team: string;
  points: number;
}

export interface DriverStandingsChartProps {
  standings: DriverStanding[];
}

export function DriverStandingsChart({ standings }: DriverStandingsChartProps) {
  // Transform data for recharts
  const chartData = standings.map((driver) => ({
    name: driver.name.split(' ').pop(), // Last name only for chart
    fullName: driver.name,
    points: driver.points,
    team: driver.team,
  }));

  // Custom tooltip
  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="driver-chart-tooltip">
          <p className="driver-chart-tooltip-name">{data.fullName}</p>
          <p className="driver-chart-tooltip-team">{data.team}</p>
          <p className="driver-chart-tooltip-points">{data.points} PTS</p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="driver-chart-container">
      {/* Chart Header */}
      <div className="driver-chart-header">
        <div className="driver-chart-top-bar" />
        <div className="driver-chart-title-section">
          <h3 className="driver-chart-title">DRIVER STANDINGS</h3>
          <div className="driver-chart-subtitle">POINTS DISTRIBUTION</div>
        </div>
      </div>

      {/* Chart */}
      <div className="driver-chart-wrapper">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart
            data={chartData}
            margin={{ top: 5, right: 5, left: -20, bottom: 0 }}
          >
            <CartesianGrid
              strokeDasharray="3 3"
              stroke="#000"
              strokeOpacity={0.1}
            />
            <XAxis
              dataKey="name"
              textAnchor="middle"
              height={40}
              tick={{ fill: '#000', fontSize: 12, fontFamily: 'monospace', fontWeight: 'bold' }}
              stroke="#000"
              strokeWidth={2}
            />
            <YAxis
              tick={{ fill: '#000', fontSize: 16, fontFamily: 'monospace', fontWeight: 'bold' }}
              stroke="#000"
              strokeWidth={2}
              label={{
                value: 'POINTS',
                angle: -90,
                position: 'insideLeft',
                style: { fill: '#C41E3A', fontFamily: 'monospace', fontWeight: 'bold', fontSize: 16 },
              }}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(196, 30, 58, 0.1)' }} />
            <Bar dataKey="points" radius={[4, 4, 0, 0]}>
              {chartData.map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={getTeamColor(entry.team)}
                  stroke="#000"
                  strokeWidth={2}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Side Stripe */}
      <div className="driver-chart-side-stripe" />
    </div>
  );
}