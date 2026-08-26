-- Fridge Factorio Stats mod
-- Provides /fridge-stats RCON command (alias /xsplit-stats) returning JSON for streaming overlays.
-- Tracks player deaths via events.
-- Compatible with Factorio 2.0 / 2.1 (Space Age).

local json = helpers and helpers.table_to_json or function(t) return game.table_to_json(t) end

-- Persistent storage
script.on_init(function()
  storage.deaths = 0
  storage.kill_cache = {}
end)

script.on_configuration_changed(function()
  storage.deaths = storage.deaths or 0
  storage.kill_cache = storage.kill_cache or {}
end)

-- Track deaths
script.on_event(defines.events.on_player_died, function(event)
  storage.deaths = (storage.deaths or 0) + 1
end)

-- Helper: safe surface name
local function surface_name(surface)
  return surface and surface.name or "nauvis"
end

-- Collect kill counts (biters / enemies killed by player force)
local function get_kills(force, surface)
  local stats = force.get_kill_count_statistics(surface)
  if not stats then return 0, {} end

  -- input_counts = entities killed *by* this force
  local total = 0
  local by_type = {}
  for name, count in pairs(stats.input_counts or {}) do
    total = total + count
    by_type[name] = count
  end
  return total, by_type
end

-- Collect current alerts from connected players
local function get_alerts()
  local alerts = {}
  for _, player in pairs(game.connected_players) do
    local ok, player_alerts = pcall(function()
      return player.get_alerts({})
    end)
    if ok and player_alerts then
      for surface_index, type_map in pairs(player_alerts) do
        for alert_type, alert_list in pairs(type_map) do
          for _, alert in pairs(alert_list) do
            local entry = {
              type = tostring(alert_type),
              surface = surface_index,
              tick = game.tick
            }
            if alert.target and alert.target.valid then
              entry.entity = alert.target.name
              entry.position = {x = alert.target.position.x, y = alert.target.position.y}
            end
            if alert.message then
              entry.message = alert.message
            end
            table.insert(alerts, entry)
          end
        end
      end
    end
  end
  return alerts
end

-- Power is intentionally left as a stub here.
-- Accurate production / consumption / accumulator data comes from the companion
-- "Wiretap – Stats Exporter" mod (hmph-wiretap) which the Node bridge automatically merges.
-- Scanning every electric entity every few seconds would hurt UPS on large bases.
local function get_power_approx(force)
  return {
    production_watts_approx = 0,
    note = "Install 'Wiretap – Stats Exporter' (hmph-wiretap) for live power production & consumption."
  }
end

-- Main data collector
local function collect_stats()
  local force = game.forces["player"] or game.forces[1]
  if not force then
    return { error = "No player force found" }
  end

  local surface = game.surfaces["nauvis"] or game.surfaces[1]
  local kills_total, kills_by_type = get_kills(force, surface)

  -- Research
  local research = {
    current = nil,
    progress = 0,
    queue = {},
    researched_count = 0
  }
  if force.current_research then
    research.current = force.current_research.name
    research.progress = force.research_progress or 0
  end
  if force.research_queue then
    for _, tech in pairs(force.research_queue) do
      table.insert(research.queue, type(tech) == "string" and tech or (tech.name or tostring(tech)))
    end
  end
  -- Count researched
  local researched = 0
  local total_tech = 0
  for name, tech in pairs(force.technologies) do
    total_tech = total_tech + 1
    if tech.researched then
      researched = researched + 1
    end
  end
  research.researched_count = researched
  research.total_technologies = total_tech

  -- Evolution (enemy force)
  local evolution = 0
  if game.forces["enemy"] then
    evolution = game.forces["enemy"].get_evolution_factor(surface) or 0
  end

  local data = {
    tick = game.tick,
    game_time_seconds = math.floor(game.tick / 60),
    deaths = storage.deaths or 0,
    kills = {
      total = kills_total,
      by_type = kills_by_type  -- can be large; overlay can ignore details
    },
    research = research,
    evolution = evolution,
    alerts = get_alerts(),
    power = get_power_approx(force),
    players_online = #game.connected_players,
    surface = surface_name(surface)
  }

  return data
end

-- RCON / console command
local function print_stats(command)
  local data = collect_stats()
  local success, encoded = pcall(json, data)
  if success then
    rcon.print(encoded)
  else
    rcon.print('{"error":"json encode failed"}')
  end
end

commands.add_command("fridge-stats", "Return JSON stats for Fridge overlays", print_stats)
-- kept so an old bridge still works until you update the Node process
commands.add_command("xsplit-stats", "Legacy alias for /fridge-stats", print_stats)

-- Optional: also write file every ~5 seconds for file-based consumers
local write_interval = 300  -- ticks (~5s at 60ups)
script.on_nth_tick(write_interval, function()
  local data = collect_stats()
  -- Trim kills_by_type to keep file small (top killers only)
  if data.kills and data.kills.by_type then
    local sorted = {}
    for k, v in pairs(data.kills.by_type) do
      table.insert(sorted, {name = k, count = v})
    end
    table.sort(sorted, function(a, b) return a.count > b.count end)
    local top = {}
    for i = 1, math.min(15, #sorted) do
      top[sorted[i].name] = sorted[i].count
    end
    data.kills.by_type = top
  end
  pcall(function()
    helpers.write_file("fridge-stats/stats.json", json(data), false)
  end)
end)

-- Remote interface for other mods
local stats_interface = {
  get_stats = function()
    return collect_stats()
  end,
  get_deaths = function()
    return storage.deaths or 0
  end
}
remote.add_interface("fridge-stats", stats_interface)
remote.add_interface("xsplit-stats", stats_interface)
