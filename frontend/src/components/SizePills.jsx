import React from 'react'

export default function SizePills({ sizes }) {
  return (
    <div className="flex flex-wrap gap-1">
      {sizes.map((s) => (
        <span
          key={s.size}
          title={s.available ? `${s.size}: in stock` : `${s.size}: sold out`}
          className={`rounded border px-1.5 py-0.5 text-xs font-medium ${
            s.available ? 'border-line text-ink' : 'border-line text-gray-400 line-through'
          }`}
        >
          {s.size}
        </span>
      ))}
    </div>
  )
}
