Parent = {
	_id = "parent",
}

-- yazi-flow: with the launcher's anchor active (components/current.lua owns `Flow`),
-- the parent listing is positioned so the highlighted CWD keeps the row the directory was
-- decided on (`Flow.keep`) and does not follow the middle pane's cursor, and the entries
-- are drawn from there. `Folder.offset` cannot go
-- negative, so a listing with too few entries above the CWD is padded with blank rows.
local function flow_window(folder, height)
	local target = math.min(Flow.keep or Flow.anchor, math.max(0, height - 1))
	local cursor = folder.cursor
	local offset = math.max(0, cursor - target)
	local pad = math.min(math.max(0, target - cursor), math.max(0, height - 1))
	local stop = math.min(#folder.files, offset + math.max(0, height - pad))

	return offset, pad, stop
end

function Parent:new(area, tab)
	return setmetatable({
		_area = area,
		_tab = tab,
		_folder = tab.parent,
	}, { __index = self })
end

function Parent:reflow() return { self } end

local function entry(f, width)
	local entity = Entity:new(f)
	local l, r = entity:redraw(), Linemode:new(f):redraw()
	local max = math.max(0, width - r:width())
	l:truncate { max = max, ellipsis = entity:ellipsis(max) }
	return l, r
end

function Parent:redraw()
	if not self._folder then
		return {}
	end

	local left, right = {}, {}
	local width = self._area.w

	if Flow.anchor and Flow.keep then
		local offset, pad, stop = flow_window(self._folder, self._area.h)

		for _ = 1, pad do
			left[#left + 1], right[#right + 1] = ui.Line(""), ui.Line("")
		end
		for i = offset + 1, stop do
			local l, r = entry(self._folder.files[i], width)
			left[#left + 1], right[#right + 1] = l, r
		end
	else
		for _, f in ipairs(self._folder.window) do
			local l, r = entry(f, width)
			left[#left + 1], right[#right + 1] = l, r
		end
	end

	return {
		ui.List(left):area(self._area),
		ui.Text(right):area(self._area):align(ui.Align.RIGHT),
	}
end

-- Mouse events
function Parent:click(event, up)
	if up or event.is_middle then
		return
	end

	local y = event.y - self._area.y + 1
	if Flow.anchor and Flow.keep then
		local offset, pad = flow_window(self._folder, self._area.h)
		local files = self._folder.files
		local idx = offset + (y - pad)

		if y > pad and idx >= 1 and idx <= #files then
			Entity:new(files[idx]):click(event, up)
		elseif event.is_left then
			ya.emit("leave", {})
		end
		return
	end

	local window = self._folder.window
	if window[y] then
		Entity:new(window[y]):click(event, up)
	elseif event.is_left then
		ya.emit("leave", {})
	end
end

function Parent:scroll(event, step) end

function Parent:touch(event, step) end
