-- block_chart: add `facet` param so the agent (and Inspector) can build
-- small-multiples charts (one panel per group, each with own y-axis +
-- UCL/LCL). Sidecar reads from seed.py at startup so its catalog is
-- already current; this migration just keeps Java's pb_blocks mirror in
-- sync for the Inspector UI.

UPDATE pb_blocks
SET param_schema = jsonb_set(
        param_schema::jsonb,
        '{properties,facet}',
        '{"type":"string","x-column-source":"input.data","title":"facet (split into N independent charts, one per group)"}'::jsonb,
        true
    )::text,
    updated_at = NOW()
WHERE name = 'block_chart';

-- Append a short hint to the description without rewriting the whole
-- prose (sidecar's seed.py is the SSOT for the verbose copy).
UPDATE pb_blocks
SET description = description ||
    E'\n\n== facet (added v4) ==\n' ||
    E'  facet="<column>" → emit one independent chart per distinct value;\n' ||
    E'  use when y-scales differ across groups (e.g. SPC chart_name = {C,P,R,Xbar,S}).\n' ||
    E'  Pipeline pattern: process_history → spc_long_form → chart(facet="chart_name", ...)\n' ||
    E'  ⚠ vs color: color = N lines on ONE chart (same y); facet = N charts (own y).',
    updated_at = NOW()
WHERE name = 'block_chart'
  AND description NOT LIKE '%facet (added v4)%';
