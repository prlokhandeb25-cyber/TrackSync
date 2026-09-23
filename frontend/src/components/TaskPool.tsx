import React from 'react'

interface Task {
  id: string
  department: string
  task_type: string
  section_id: string
  duration_min: number
  priority: number
  category: string
  status: string
}

interface TaskPoolProps {
  tasks: Task[]
}

export const TaskPool: React.FC<TaskPoolProps> = ({ tasks }) => {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-xl">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-blue-500"></span>
          Active Maintenance Task Pool
        </h3>
        <span className="text-xs text-slate-400">{tasks.length} active tasks</span>
      </div>

      <div className="overflow-x-auto max-h-64">
        <table className="w-full text-xs text-left text-slate-300">
          <thead className="bg-slate-950 text-slate-400 border-b border-slate-800 uppercase text-[10px]">
            <tr>
              <th className="p-2">ID</th>
              <th className="p-2">Dept</th>
              <th className="p-2">Type</th>
              <th className="p-2">Section</th>
              <th className="p-2">Duration</th>
              <th className="p-2">Priority</th>
              <th className="p-2">Category</th>
              <th className="p-2">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {tasks.map(t => (
              <tr key={t.id} className="hover:bg-slate-800/40">
                <td className="p-2 font-mono text-slate-200">{t.id}</td>
                <td className="p-2 font-semibold text-indigo-400">{t.department}</td>
                <td className="p-2 text-slate-300">{t.task_type.replace(/_/g, ' ')}</td>
                <td className="p-2 font-mono text-slate-400">{t.section_id}</td>
                <td className="p-2">{t.duration_min} min</td>
                <td className="p-2 font-semibold text-amber-400">P{t.priority}</td>
                <td className="p-2">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${t.category === 'DEMAND' ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30' : 'bg-blue-500/20 text-blue-400 border border-blue-500/30'}`}>
                    {t.category}
                  </span>
                </td>
                <td className="p-2 font-medium text-emerald-400">{t.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
