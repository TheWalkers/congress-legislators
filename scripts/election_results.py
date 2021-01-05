# Update the data files according to the results of
# a general election using a spreadsheet of election
# results and prepares for a new Congress. This script
# does the following:
#
# * Adds end dates to all current leadership roles since
#   leadership resets in both chambers each Congress.
# * Brings senators not up for relection and the Puerto
#   Rico resident commissioner in off-years forward
#   unchanged.
# * Creates new legislator entries for new people in
#   the election results spreadsheet. The next available
#   GovTrack ID is assigned to each new legislator.
# * Creates new terms for each election winner in the
#   election results spreadsheet (incumbents and new
#   legislators).
# * Clears the committee-membership-current.yaml file
#   since all House and Senate committees reset at the
#   start of a new Congress.
# * Clears out the social media entries for legislators
#   no longer serving.
#
# Usage:
# * Save the spreadsheet to archive/election_results_{year}.csv.
# * Edit the ELECTION_YEAR constant below.
# * Make sure the legislators-{current,historical}.yaml files are 
#   clean -- i.e. if you've run this script, reset these files
#   before running it again.
# * Run this script.

import collections, csv, re
from utils import load_data, save_data

ELECTION_YEAR = 2020

def run():
	# Compute helper constants.
	SENATE_CLASS = ((ELECTION_YEAR-2) % 6) // 2 + 1

	# Open existing data.
	print("Opening legislator data...")
	legislators_historical = load_data("legislators-historical.yaml")
	legislators_current = load_data("legislators-current.yaml")

	# New member data.
	party_map = { "R": "Republican", "D": "Democrat", "I": "Independent" }
	new_legislators = []

	# Only one class of senators was up for election. Mark all other
	# senators as still serving. Additionally, in off years for the
	# four-year-termed resident commissioner of Puerto Rico, mark
	# that person as still serving also.
	current = []
	for p in legislators_current:
		if p["terms"][-1]["type"] == "sen" and p["terms"][-1]["class"] != SENATE_CLASS:
			current.append(p["id"]["govtrack"])
		if p["terms"][-1]["state"] == "PR" and (ELECTION_YEAR % 4 == 0):
			current.append(p["id"]["govtrack"])

	# Map govtrack IDs to exiting legislators.
	govtrack_id_map = { }
	for entry in legislators_historical + legislators_current:
		govtrack_id_map[entry['id']['govtrack']] = entry

	# Get highest existing GovTrack ID to know where to start for assigning new IDs.
	next_govtrack_id = max(p['id']['govtrack'] for p in (legislators_historical+legislators_current))

	# Load spreadsheet of Senate election results.
	print("Applying election results...")
	election_results = csv.DictReader(open("archive/election_results_{year}.csv".format(year=ELECTION_YEAR)))
	for row in election_results:
		if row['Race'] == "": break # end of spreadsheet

		# Get state and district from race code. An empty
		# district means a senate race.
		state, district = re.match(r"^([A-Z]{2})(\d*)$", row["Race"]).groups()

		if row['GovTrack ID'] != "":
			# Use the GovTrack ID to get the legislator who won, which might be
			# the incumbent or a representative elected to the senate, or a
			# someone who used to serve in Congress, etc.
			p = govtrack_id_map[int(row['GovTrack ID'])]
		elif row['Incumbent Win? Y/N'] == 'Y':
			# Use the race code to get the legislator who won.
			incumbent = [p for p in legislators_current
			             if  p["terms"][-1]["type"] == ("sen" if district == "" else "rep")
			             and p["terms"][-1]["state"] == state
			             and ((p["terms"][-1]["district"] == int(district)) if district != ""
		             	 else (p["terms"][-1]["class"] == SENATE_CLASS))
			            ]
			if len(incumbent) != 1:
				raise ValueError("Could not find incumbent.")
			p = incumbent[0]
		elif row['Incumbent Win? Y/N'] == 'N':
			# Make a new legislator entry.
			next_govtrack_id += 1
			p = collections.OrderedDict([
				("id", collections.OrderedDict([
					#("bioguide", row['Bioguide ID']),
					("fec", [row['FEC.gov ID']]),
					("govtrack", next_govtrack_id),
					#("opensecrets", None), # don't know yet
					#("votesmart", int(row['votesmart'])), # not doing this anymore
					#("wikipedia", row['Wikipedia Page Name']), # will convert from Wikidata
					("wikidata", row['Wikidata ID']),
					#("ballotpedia", row['Ballotpedia Page Name']),
				])),
				("name", collections.OrderedDict([
					("first", row['First Name']),
					("middle", row['Middle Name']),
					("last", row['Last Name']),
					("suffix", row['Suffix']),
					#("official_full", mi.find('official-name').text), #not available yet
				])),
				("bio", collections.OrderedDict([
				 	("gender", row['Gender (M/F)']),
				 	("birthday", row['Birthday (YYYY-MM-DD)']),
				])),
				("terms", []),
			])

			# Delete name keys that were filled with Nones.
			for k in list(p["name"]): # clone key list before modifying dict
				if not p["name"][k]:
					del p["name"][k]

			new_legislators.append(p)
		else:
			# There is no winner in this election. The incumbent
			# will not be marked as still serving, so they'll
			# be moved to the historical file, and no person will
			# be added for this race.
			print("No election result for", row["Race"], row["Incumbent Win? Y/N"])
			continue

		# Add to array marking this legislator as currently serving.
		current.append(p['id']['govtrack'])

		# Add a new term.
		if district == "": # Senate race
			term = collections.OrderedDict([
				("type", "sen"),
				("start", "{next_year}-01-03".format(next_year=ELECTION_YEAR+1)),
				("end", "{in_six_years}-01-03".format(in_six_years=ELECTION_YEAR+1+6)),
				("state", state),
				("class", SENATE_CLASS),
				("state_rank", None), # computed later
			])
		else:
			term = collections.OrderedDict([
				("type", "rep"),
				("start", "{next_year}-01-03".format(next_year=ELECTION_YEAR+1)),
				("end", "{in_two_years}-01-03".format(in_two_years=ELECTION_YEAR+1+2)),
				("state", state),
				("district", int(district)),
			])
		# If party is given in the table (for some incumbents and
		# all new winners), use it. Otherwise just make a field so
		# it's in the right order.
		term.update(collections.OrderedDict([
			("party", party_map[row['Party']] if row['Party'] else None),
		]))
		p['terms'].append(term)
		if term['party'] == "Independent":
			term["caucus"] = row['Caucus']

		if len(p['terms']) > 1 and p["terms"][-2]["type"] == term["type"]:
			# This is an incumbent (or at least served in the same chamber previously).
			# Copy some fields forward that are likely to remain the same, if we
			# haven't already set them.
			for k in ('party', 'url', 'rss_url'):
				if k in p['terms'][-2] and not term.get(k):
					term[k] = p['terms'][-2][k]

	# End any current leadership roles.
	for p in legislators_current:
		for r in p.get('leadership_roles', []):
			if not r.get('end'):
				r['end'] = "{next_year}-01-03".format(next_year=ELECTION_YEAR+1)

	# Split the legislators back into the historical and current lists:

	# Move previously-current legislators into the historical list
	# if they are no longer serving, in the order that they appear
	# in the current list.
	for p in legislators_current:
		if p["id"]["govtrack"] not in current:
			legislators_historical.append(p)
	legislators_current = [p for p in legislators_current if p['id']['govtrack'] in current]

	# Move former legislators forward into the current list if they
	# are returning to Congress, in the order they appear in the
	# historical list.
	for p in legislators_historical:
		if p["id"]["govtrack"] in current:
			legislators_current.append(p)
	legislators_historical = [p for p in legislators_historical if p['id']['govtrack'] not in current]

	# Add new legislators in the order they occur in the election
	# results spreadsheet.
	for p in new_legislators:
		legislators_current.append(p)

	# Re-compute the state_rank junior/senior status of all senators.
	# We'll get this authoritatively from the Senate by senate_contacts.py
	# once that data is up, but we'll make an educated guess now.
	state_rank_assignment = set()
	# Senior senators not up for re-election keep their status:
	for p in legislators_current:
		term = p['terms'][-1]
		if term['type'] == 'sen' and term['class'] != SENATE_CLASS and term['state_rank'] == 'senior':
			state_rank_assignment.add(p['terms'][-1]['state'])
	# Senior senators who won re-election pull their status forward:
	for p in legislators_current:
		term = p['terms'][-1]
		if term['state'] in state_rank_assignment: continue # we already assigned the senior senator
		if term['type'] == 'sen' and term['class'] == SENATE_CLASS and len(p['terms']) > 1 \
			and p['terms'][-2]['type'] == 'sen' and p['terms'][-2]['state'] == term['state'] and p['terms'][-2]['state_rank'] == 'senior':
			term['state_rank'] = 'senior'
			state_rank_assignment.add(p['terms'][-1]['state'])
	# Junior senators not up for re-election become senior if we didn't see a senior senator yet:
	for p in legislators_current:
		term = p['terms'][-1]
		if term['state'] in state_rank_assignment: continue # we already assigned the senior senator
		if term['type'] == 'sen' and term['class'] != SENATE_CLASS and term['state_rank'] == 'junior':
			term['state_rank'] = 'senior'
			state_rank_assignment.add(p['terms'][-1]['state'])
	# Remaining senators are senior if we haven't seen a senior senator yet, else junior:
	for p in legislators_current:
		term = p['terms'][-1]
		if term['type'] == 'sen' and term['state_rank'] is None:
			if term['state'] not in state_rank_assignment:
				term['state_rank'] = 'senior'
				state_rank_assignment.add(term['state'])
			else:
				term['state_rank'] = 'junior'

	# Save.
	print("Saving legislator data...")
	save_data(legislators_current, "legislators-current.yaml")
	save_data(legislators_historical, "legislators-historical.yaml")

	# Run the sweep script to clear out data that needs to be cleared out
	# for legislators that are gone.
	import sweep
	sweep.run()

	# Clears committee membership.
	save_data([], "committee-membership-current.yaml")

if __name__ == "__main__":
	run()
