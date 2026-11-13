#!/usr/local/bin/perl
# Shared functions for the GitHub Actions Runners Webmin module.
# The module only reads the JSON status file written by ghrunners-collector;
# it never talks to GitHub or Docker itself and holds no secrets.

use strict;
use warnings;
no warnings 'redefine';
no warnings 'uninitialized';
BEGIN { push(@INC, ".."); };
use WebminCore;
use JSON::PP ();
use Time::Local ();
&init_config();
our (%config, %text);

# read_status() -> (\%status, $error)
sub read_status
{
my $file = $config{'status_file'} || '/var/lib/ghrunners/status.json';
return (undef, &text('index_enofile', &html_escape($file)))
	if (!-r $file);
my $raw = &read_file_contents($file);
return (undef, &text('index_eempty', &html_escape($file)))
	if (!defined($raw) || $raw !~ /\S/);
my $data = eval { JSON::PP->new->utf8->decode($raw) };
return (undef, &text('index_ejson', &html_escape($file),
		     &html_escape($@ =~ /^(.*?) at /s ? $1 : $@)))
	if (!$data || ref($data) ne 'HASH');
return ($data, undef);
}

# iso_to_epoch("2026-11-10T17:00:00Z") -> epoch seconds, or undef
sub iso_to_epoch
{
my ($iso) = @_;
return if (!$iso);
if ($iso =~ /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.\d+)?(Z|([+-])(\d\d):?(\d\d))?$/) {
	my $t = eval { Time::Local::timegm($6, $5, $4, $3, $2 - 1, $1) };
	return if (!defined($t));
	if ($8) {
		my $off = ($9 * 3600 + $10 * 60) * ($8 eq '+' ? 1 : -1);
		$t -= $off;
		}
	return $t;
	}
return;
}

# human_duration(seconds) -> "3m 20s"
sub human_duration
{
my ($s) = @_;
return '-' if (!defined($s));
$s = 0 if ($s < 0);
return $s."s" if ($s < 60);
return int($s / 60)."m ".($s % 60)."s" if ($s < 3600);
return int($s / 3600)."h ".int(($s % 3600) / 60)."m" if ($s < 86400);
return int($s / 86400)."d ".int(($s % 86400) / 3600)."h";
}

# since(iso) -> human duration from that time until now
sub since
{
my ($iso) = @_;
my $t = &iso_to_epoch($iso);
return defined($t) ? &human_duration(time() - $t) : '-';
}

# runner_state(\%runner) -> 'busy' | 'idle' | 'offline'
sub runner_state
{
my ($r) = @_;
return 'offline' if ($r->{'status'} ne 'online');
return $r->{'busy'} ? 'busy' : 'idle';
}

my %badge_color = (
	'busy'    => '#d97706',
	'idle'    => '#16a34a',
	'offline' => '#6b7280',
	'stuck'   => '#dc2626',
	'queued'  => '#2563eb',
	);

# badge(kind, text) -> small coloured label HTML
sub badge
{
my ($kind, $label) = @_;
my $c = $badge_color{$kind} || '#6b7280';
return "<span class='ghr-badge' style='display:inline-block;padding:1px 8px;".
       "border-radius:10px;font-size:90%;font-weight:600;color:#fff;".
       "background:$c;white-space:nowrap'>".&html_escape($label)."</span>";
}

# is_self_hosted(\@labels) -> true if a job targets self-hosted runners
sub is_self_hosted
{
my ($labels) = @_;
return scalar(grep { lc($_) eq 'self-hosted' } @{$labels || []});
}

# can_run(\%job, \@runners) -> number of online runners whose labels cover the
# job's requested labels
sub can_run
{
my ($job, $runners) = @_;
my @want = map { lc($_) } @{$job->{'labels'} || []};
my $n = 0;
RUNNER: foreach my $r (@$runners) {
	next if ($r->{'status'} ne 'online');
	my %have = map { lc($_) => 1 } @{$r->{'labels'} || []};
	foreach my $w (@want) {
		next RUNNER if (!$have{$w});
		}
	$n++;
	}
return $n;
}

# bar(fraction) -> small horizontal usage bar HTML
sub bar
{
my ($frac) = @_;
return '' if (!defined($frac));
$frac = 0 if ($frac < 0);
$frac = 1 if ($frac > 1);
my $pct = int($frac * 100 + 0.5);
my $c = $frac >= 0.9 ? '#dc2626' : $frac >= 0.75 ? '#d97706' : '#16a34a';
return "<span style='display:inline-block;vertical-align:middle;width:120px;".
       "height:8px;border-radius:4px;background:rgba(127,127,127,.25);".
       "overflow:hidden;margin-right:6px'><span style='display:block;height:100%;".
       "width:$pct%;background:$c'></span></span>$pct%";
}

# gauge(fraction, label, detail-html) -> ring gauge HTML, in the style of
# Webmin's system information dashboard. An undefined fraction draws an empty
# ring with "-".
sub gauge
{
my ($frac, $label, $detail) = @_;
my $pi = 3.14159265;
my $r = 46;
my $circ = 2 * $pi * $r;
my ($pct, $arc, $c) = ('-', 0, '#16a34a');
if (defined($frac)) {
	$frac = 0 if ($frac < 0);
	$pct = int($frac * 100 + 0.5);
	$arc = $circ * ($frac > 1 ? 1 : $frac);
	$c = $frac >= 0.9 ? '#dc2626' : $frac >= 0.75 ? '#d97706' : '#16a34a';
	}
my $ticks = '';
for (my $i = 0; $i < 40; $i++) {
	my $a = $i * 2 * $pi / 40;
	my ($in, $out) = $i % 5 ? (52, 55) : (51, 57);
	$ticks .= sprintf("<line x1='%.1f' y1='%.1f' x2='%.1f' y2='%.1f'/>",
			  60 + $in * sin($a), 60 - $in * cos($a),
			  60 + $out * sin($a), 60 - $out * cos($a));
	}
my $aria = &html_escape(defined($frac) ? "$label: $pct%" : $label);
$aria =~ s/&amp;(\w+;)/&$1/g;
return "<div class='ghr-gauge' style='width:150px;text-align:center'>".
       "<svg viewBox='0 0 120 120' width='120' height='120' role='img' ".
       "aria-label='$aria'>".
       "<g stroke='currentColor' stroke-opacity='.3' stroke-width='1'>$ticks</g>".
       "<circle cx='60' cy='60' r='$r' fill='none' stroke='currentColor' ".
       "stroke-opacity='.12' stroke-width='5'/>".
       ($arc > 0 ? sprintf("<circle cx='60' cy='60' r='$r' fill='none' ".
			   "stroke='$c' stroke-width='5' ".
			   "stroke-dasharray='%.2f %.2f' ".
			   "transform='rotate(-90 60 60)'/>", $arc, $circ) : "").
       "<text x='60' y='60' text-anchor='middle' dominant-baseline='central' ".
       "fill='currentColor' fill-opacity='.8' font-size='26'>$pct".
       (defined($frac) ? "<tspan font-size='14' dx='1'>%</tspan>" : "").
       "</text></svg>".
       "<div style='font-size:85%;font-weight:600;text-transform:uppercase;".
       "letter-spacing:.03em;opacity:.65'>$label</div>".
       "<div style='font-size:85%;opacity:.8'>$detail</div></div>";
}

# size(bytes) -> human size or '-'
sub size
{
my ($b) = @_;
return defined($b) ? &nice_size($b) : '-';
}

1;
