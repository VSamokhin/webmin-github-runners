#!/usr/local/bin/perl
# Show self-hosted GitHub Actions runners, queued jobs and host resources.

use strict;
use warnings;
no warnings 'redefine';
no warnings 'uninitialized';
require './ghrunners-lib.pl';
our (%config, %text, %in);
&ReadParse();

my ($st, $err) = &read_status();
my $refresh = int($config{'refresh'} // 30);
my $stale_after = int($config{'stale_after'} || 300);
my $stuck_after = int($config{'stuck_after'} || 900);
my $show_hosted = $config{'show_hosted'};

# Last update time. Shown in the page body, not in ui_print_header's right
# slot: Authentic turns that slot into an icon button bar and clips plain text.
my $age;
my $updated = '';
if ($st) {
	my $t = &iso_to_epoch($st->{'generated_at'});
	$age = defined($t) ? time() - $t : undef;
	$updated = &text('index_updated', &human_duration($age)).
		   ($refresh > 0 ? " &middot; ".&text('index_autorefresh', $refresh) : "");
	}

# Auto refresh. Works with the Authentic theme's in-page navigation: the timer
# only fires while this page is still displayed.
my $head = '';
if ($refresh > 0) {
	my $ms = $refresh * 1000;
	$head = "<script>(function(){setTimeout(function(){".
		"if(document.getElementById('ghr-root')){location.reload();}".
		"},$ms);})();</script>";
	}

&ui_print_header(undef, $text{'index_title'}, "", "intro", 1, 1, 0, undef,
		 $head);
print "<div id='ghr-root'>\n";
print "<p class='ghr-updated' style='margin:0 0 10px;opacity:.7'>",
      "<small>$updated</small></p>\n" if ($updated);

if (!$st) {
	print &ui_alert_box($err, 'warn');
	print &ui_alert_box($text{'index_setup'}, 'info');
	print "</div>\n";
	&ui_print_footer("/", $text{'index'});
	exit;
	}

if (defined($age) && $age > $stale_after) {
	print &ui_alert_box(&text('index_stale', &human_duration($age)), 'danger');
	}
if ($st->{'schema'} && $st->{'schema'} > 1) {
	print &ui_alert_box(&text('index_schema', $st->{'schema'}), 'warn');
	}
foreach my $e (@{$st->{'errors'} || []}) {
	print &ui_alert_box(&html_escape($e), 'warn');
	}

my @scopes = @{$st->{'scopes'} || []};
my %org_runners;
foreach my $s (grep { $_->{'type'} eq 'org' } @scopes) {
	push(@{$org_runners{lc($s->{'name'})}}, @{$s->{'runners'} || []});
	}

# ---- Host resources --------------------------------------------------------
# Shown first, as ring gauges: CPU load, memory and each disk.
my $h = $st->{'host'} || {};
my @gauges;
if ($h->{'load'}) {
	my $cpus = $h->{'cpus'} || 1;
	push(@gauges, &gauge($h->{'load'}->[0] / $cpus, $text{'host_cpu'},
		"<span title='$text{'host_loadavg'}'>".&html_escape(join(' / ', @{$h->{'load'}}))."</span>"."<br>".
		&text('host_cpus', $cpus)));
	}
if ($h->{'mem_total'}) {
	my $used = $h->{'mem_total'} - $h->{'mem_available'};
	push(@gauges, &gauge($used / $h->{'mem_total'}, $text{'host_mem'},
		&size($used)." / ".&size($h->{'mem_total'})));
	}
foreach my $d (@{$h->{'disks'} || []}) {
	push(@gauges, &gauge($d->{'error'} || !$d->{'total'} ? undef :
				1 - $d->{'free'} / $d->{'total'},
		&text('host_disk', &html_escape($d->{'label'})),
		$d->{'error'} ? &html_escape($d->{'error'}) :
			&text('host_free', &size($d->{'free'}), &size($d->{'total'}))));
	}
if (@gauges) {
	print &ui_columns_start([ &text('host_title', &html_escape($h->{'hostname'})) ],
				100);
	print &ui_columns_row([ "<div class='ghr-gauges' style='display:flex;".
				"flex-wrap:wrap;gap:8px 28px;padding:6px 0'>".
				join('', @gauges)."</div>" ]);
	print &ui_columns_end();
	}

# ---- Summary -------------------------------------------------------------
my $sum = $st->{'summary'} || {};
my @queued;
foreach my $s (@scopes) {
	my ($owner) = split(/\//, $s->{'name'});
	my @pool = (@{$s->{'runners'} || []}, @{$org_runners{lc($owner)} || []});
	foreach my $j (@{$s->{'queued'} || []}) {
		my $hosted = !&is_self_hosted($j->{'labels'});
		next if ($hosted && !$show_hosted);
		push(@queued, { %$j, 'scope' => $s, 'hosted' => $hosted,
				'matching' => $hosted ? undef : &can_run($j, \@pool) });
		}
	}
my $rl = $st->{'rate_limit'} || {};
print &ui_columns_start([ $text{'sum_runners'}, $text{'sum_busy'},
			  $text{'sum_idle'}, $text{'sum_offline'},
			  $text{'sum_queued'}, $text{'sum_rate'} ], 100);
print &ui_columns_row([
	"<b>".int($sum->{'runners'})."</b>",
	&badge('busy', int($sum->{'busy'})),
	&badge('idle', int($sum->{'idle'})),
	&badge($sum->{'offline'} ? 'stuck' : 'offline', int($sum->{'offline'})),
	&badge(@queued ? 'queued' : 'offline', scalar(@queued)),
	defined($rl->{'remaining'}) ?
		&html_escape("$rl->{'remaining'} / $rl->{'limit'}") : '-',
	]);
print &ui_columns_end();

# ---- Runners -------------------------------------------------------------
my %order = ('busy' => 0, 'idle' => 1, 'offline' => 2);
my @runners;
foreach my $s (@scopes) {
	push(@runners, map { { %$_, 'scope' => $s } } @{$s->{'runners'} || []});
	}
@runners = sort { $order{&runner_state($a)} <=> $order{&runner_state($b)} ||
		  lc($a->{'name'}) cmp lc($b->{'name'}) } @runners;

print &ui_columns_start([ $text{'run_name'}, $text{'run_state'},
			  $text{'run_scope'}, $text{'run_labels'},
			  $text{'run_job'}, $text{'run_for'} ], 100, 0, undef,
			$text{'run_title'});
if (!@runners) {
	print &ui_columns_row([ "<i>$text{'run_none'}</i>", '', '', '', '', '' ]);
	}
foreach my $r (@runners) {
	my $state = &runner_state($r);
	my $j = $r->{'job'};
	my $job = '';
	if ($j) {
		$job = &ui_link($j->{'url'}, &html_escape($j->{'name'}), undef,
				"target='_blank'").
		       " <small>(".&html_escape($j->{'workflow'}).
		       ($j->{'branch'} ? " &middot; ".&html_escape($j->{'branch'}) : "").
		       ")</small>";
		}
	elsif ($state eq 'busy') {
		$job = "<i>$text{'run_otherjob'}</i>";
		}
	my @labels = grep { !/^(self-hosted|linux|x64|arm64|macos|windows)$/i }
			  @{$r->{'labels'} || []};
	print &ui_columns_row([
		"<b>".&html_escape($r->{'name'})."</b>".
		  ($r->{'os'} ? " <small>".&html_escape($r->{'os'})."</small>" : ""),
		&badge($state, $text{'state_'.$state}),
		&ui_link($r->{'scope'}->{'url'}, &html_escape($r->{'scope'}->{'name'}),
			 undef, "target='_blank'"),
		&html_escape(join(', ', @labels)),
		$job,
		$j ? &since($j->{'started_at'}) : '',
		]);
	}
print &ui_columns_end();

# ---- Queue ---------------------------------------------------------------
@queued = sort { ($a->{'created_at'} cmp $b->{'created_at'}) } @queued;
print &ui_columns_start([ $text{'q_job'}, $text{'q_repo'}, $text{'q_labels'},
			  $text{'q_waiting'}, $text{'q_state'} ], 100, 0, undef,
			$text{'q_title'});
if (!@queued) {
	print &ui_columns_row([ "<i>$text{'q_none'}</i>", '', '', '', '' ]);
	}
foreach my $j (@queued) {
	my $t = &iso_to_epoch($j->{'created_at'});
	my $wait = defined($t) ? time() - $t : undef;
	my $state;
	if ($j->{'hosted'}) {
		$state = &badge('offline', $text{'q_hosted'});
		}
	elsif (!$j->{'matching'}) {
		$state = &badge('stuck', $text{'q_nomatch'});
		}
	elsif (defined($wait) && $wait > $stuck_after) {
		$state = &badge('stuck', $text{'q_slow'});
		}
	else {
		$state = &badge('queued', &text('q_waiting_for', $j->{'matching'}));
		}
	print &ui_columns_row([
		&ui_link($j->{'url'} || $j->{'run_url'}, &html_escape($j->{'name'}),
			 undef, "target='_blank'").
		  " <small>(".&html_escape($j->{'workflow'}).
		  ($j->{'branch'} ? " &middot; ".&html_escape($j->{'branch'}) : "").
		  ")</small>",
		&html_escape($j->{'scope'}->{'name'}),
		&html_escape(join(', ', @{$j->{'labels'} || []})),
		&human_duration($wait),
		$state,
		]);
	}
print &ui_columns_end();

# ---- Containers ----------------------------------------------------------
if (ref($st->{'containers'}) eq 'ARRAY' && @{$st->{'containers'}}) {
	my @cs = sort { ($b->{'state'} eq 'running') <=> ($a->{'state'} eq 'running') ||
			$a->{'name'} cmp $b->{'name'} } @{$st->{'containers'}};
	print &ui_columns_start([ $text{'c_name'}, $text{'c_state'}, $text{'c_cpu'},
				  $text{'c_mem'} ], 100, 0, undef, $text{'c_title'});
	foreach my $c (@cs) {
		my $running = $c->{'state'} eq 'running';
		my $mem = '';
		if (defined($c->{'mem_bytes'})) {
			my $lim = $c->{'mem_limit'};
			my $hostmem = $h->{'mem_total'};
			$mem = ($lim && (!$hostmem || $lim < $hostmem) ?
				  &bar($c->{'mem_bytes'} / $lim)." " : "").
			       "<small>".&size($c->{'mem_bytes'}).
			       ($lim && (!$hostmem || $lim < $hostmem) ? " / ".&size($lim) : "").
			       "</small>";
			}
		print &ui_columns_row([
			"<b>".&html_escape($c->{'name'})."</b>".
			  ($c->{'image'} ? " <small>".&html_escape($c->{'image'})."</small>" : ""),
			&badge($running ? 'idle' : 'offline', $c->{'state'}).
			  " <small>".&html_escape($c->{'status'})."</small>",
			defined($c->{'cpu_percent'}) ?
				&html_escape(sprintf("%.1f%%", $c->{'cpu_percent'})) : '-',
			$mem,
			]);
		}
	print &ui_columns_end();
	}

print "<p><small>".&text('index_footer', &html_escape($st->{'collector'}),
			 &html_escape($st->{'generated_at'}),
			 int($st->{'duration_ms'}))."</small></p>\n";
print "</div>\n";
&ui_print_footer("/", $text{'index'});
