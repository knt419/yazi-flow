Current = {
	_id = "current",
}

-- yazi-flow -----------------------------------------------------------------
-- `YAZI_FLOW_ANCHOR` (set by the launcher) is the row the decision was made on, and it
-- never moves: the hovered entry always sits on it. The listing runs downward from it in
-- listing order, and upward from it in the opposite direction, wrapping around the ends
-- of the directory and never drawing an entry twice. So with the first entry selected the
-- last one sits right above it, and moving the selection scrolls the whole pane by one
-- row instead of rearranging it.
--
-- This file is loaded before components/parent.lua, so the shared table lives here.
Flow = Flow or {}
Flow.anchor = Flow.anchor or tonumber(os.getenv("YAZI_FLOW_ANCHOR"))
Flow.keep = Flow.keep or Flow.anchor   -- decision row (fixed for the session)

local function keep_of(height)
	if not Flow.keep then
		return nil
	end
	return math.max(0, math.min(Flow.keep, height - 1))
end

-- Row and entry index of the `k`-th entry drawn: the cursor itself, then the entries that
-- follow it below, then the ones that precede it above (wrapping around the directory ends).
-- Shared with the mouse code so both agree.
local function slot_at(k, cursor, n, keep, height)
	local down = math.max(0, height - keep - 1)
	local row, idx
	if k <= down then
		row, idx = keep + k, cursor + k
	else
		local j = k - down
		row, idx = keep - j, cursor - j
	end
	return row, idx % n
end

function Current:new(area, tab)
	return setmetatable({
		_area = area,
		_tab = tab,
		_folder = tab.current,
	}, { __index = self })
end

function Current:empty()
	local s
	if self._folder.files.filter then
		s = "No filter results"
	else
		local done, err = self._folder.stage()
		s = not done and "Loading..." or not err and "No items" or string.format("Error: %s", err)
	end

	return {
		ui.Text(s):area(self._area):align(ui.Align.CENTER):wrap(ui.Wrap.YES),
		table.unpack(Dnd:new(self._area):redraw()),
	}
end

function Current:reflow() return { self } end

local function entry(f, width)
	local entity = Entity:new(f)
	local l, r = entity:redraw(), Linemode:new(f):redraw()
	local max = math.max(0, width - r:width())
	l:truncate { max = max, ellipsis = entity:ellipsis(max) }
	return l, r
end

function Current:redraw()
	local folder = self._folder
	local files = folder.files
	local n = #files
	if n == 0 then
		return self:empty()
	end

	local width, height = self._area.w, self._area.h
	local keep = keep_of(height)

	if not keep then
		local left, right = {}, {}
		for _, f in ipairs(folder.window) do
			local l, r = entry(f, width)
			left[#left + 1], right[#right + 1] = l, r
		end

		return {
			ui.List(left):area(self._area),
			ui.Text(right):area(self._area):align(ui.Align.RIGHT),
			table.unpack(Dnd:new(self._area):redraw()),
		}
	end

	-- one slot per pane row: the cursor on the decision row, then the following entries
	-- downward, then the preceding ones upward; each entry at most once
	local cursor = folder.cursor
	local slots = {}
	for k = 0, math.min(n, height) - 1 do
		local row, idx = slot_at(k, cursor, n, keep, height)
		if row >= 0 and row < height then
			local l, r = entry(files[idx + 1], width)
			slots[row] = { l, r }
		end
	end

	local left, right = {}, {}
	for row = 0, height - 1 do
		local cell = slots[row]
		if cell then
			left[#left + 1], right[#right + 1] = cell[1], cell[2]
		else
			left[#left + 1], right[#right + 1] = ui.Line(""), ui.Line("")
		end
	end

	return {
		ui.List(left):area(self._area),
		ui.Text(right):area(self._area):align(ui.Align.RIGHT),
		table.unpack(Dnd:new(self._area):redraw()),
	}
end

-- Mouse events
function Current:click(event, up)
	if up or event.is_middle then
		return
	end

	local folder = self._folder
	local n = #folder.files
	local height = self._area.h
	local keep = keep_of(height)
	local y = event.y - self._area.y

	if not keep then
		if folder.window[y + 1] then
			Entity:new(folder.window[y + 1]):click(event, up)
		end
		return
	end

	-- invert slot_at: which entry was drawn on this row?
	local down = math.max(0, height - keep - 1)
	local k = y >= keep and (y - keep) or (down + (keep - y))
	if k < 0 or k >= math.min(n, height) then
		return
	end

	local _, idx = slot_at(k, folder.cursor, n, keep, height)
	if folder.files[idx + 1] then
		Entity:new(folder.files[idx + 1]):click(event, up)
	end
end

function Current:scroll(event, step) ya.emit("arrow", { step }) end

function Current:touch(event, step) end

function Current:drag(event) return Dnd.drag(event) end

function Current:drop(event)
	if Dnd.drop(event, self._area) then
		ui.render()
	end
end
