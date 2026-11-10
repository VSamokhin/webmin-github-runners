# Minimal stand-in for Webmin's WebminCore, enough to render the module's pages
# outside Webmin in tests. It mimics the default (non-theme) ui-lib output.
package WebminCore;
use strict;
use warnings;
no warnings 'uninitialized';
use Exporter 'import';
our @EXPORT = qw(init_config ReadParse text html_escape read_file_contents
	nice_size ui_print_header ui_print_footer ui_columns_start ui_columns_row
	ui_columns_end ui_alert_box ui_link get_module_acl);

sub init_config {
	my $dir = $ENV{'GHR_MODULE_DIR'} || '.';
	my $cfg = $ENV{'GHR_CONFIG'} || "$dir/config";
	%main::config = ();
	open(my $fh, '<', $cfg) or die "$cfg: $!";
	while (<$fh>) { chomp; $main::config{$1} = $2 if /^([^=#]+)=(.*)$/; }
	close($fh);
	%main::text = ();
	open($fh, '<', "$dir/lang/en") or die "lang/en: $!";
	while (<$fh>) { chomp; $main::text{$1} = $2 if /^([^=]+)=(.*)$/; }
	close($fh);
}
sub get_module_acl { return (); }
sub ReadParse { %main::in = (); }
sub text {
	my ($key, @args) = @_;
	my $t = $main::text{$key};
	defined($t) or die "missing lang key $key\n";
	$t =~ s/\$(\d+)/$args[$1-1]/g;
	return $t;
}
sub html_escape {
	my ($s) = @_;
	$s =~ s/&/&amp;/g; $s =~ s/</&lt;/g; $s =~ s/>/&gt;/g;
	$s =~ s/"/&quot;/g; $s =~ s/'/&#39;/g;
	return $s;
}
sub read_file_contents {
	my ($f) = @_;
	open(my $fh, '<', $f) or return undef;
	local $/; my $c = <$fh>; close($fh); return $c;
}
sub nice_size {
	my ($b) = @_;
	my @u = ('bytes', 'kB', 'MB', 'GB', 'TB');
	my $i = 0;
	while ($b >= 1024 && $i < $#u) { $b /= 1024; $i++; }
	return $i ? sprintf("%.2f %s", $b, $u[$i]) : "$b $u[0]";
}
sub ui_print_header {
	my ($sub, $title, $img, $help, $config, $nomod, $nowebmin, $right, $head) = @_;
	print "Content-type: text/html; Charset=utf-8\n\n" unless $ENV{'GHR_NO_HTTP_HEADER'};
	print "<!doctype html><html><head><meta charset='utf-8'><title>$title</title>",
	      "<style>body{font-family:sans-serif;margin:16px;background:#fff}",
	      "table.ui_columns{border-collapse:collapse;margin-bottom:14px}",
	      "table.ui_columns td{border:1px solid #ddd;padding:4px 8px}",
	      ".ui_columns_heading{background:#e8eef8}.ui_columns_heads{background:#f4f6fa}",
	      ".hdr{display:flex;justify-content:space-between;align-items:center}</style>",
	      "$head</head><body><div class='hdr'><h1>$title</h1>",
	      "<div style='text-align:right'>$right</div></div>\n";
}
sub ui_print_footer { print "<hr><a href='$_[0]'>Return to $_[1]</a></body></html>\n"; }
sub ui_columns_start {
	my ($heads, $width, $noborder, $tdtags, $title) = @_;
	my $rv = "<table class='ui_columns'".(defined($width) ? " width='$width%'" : "").">\n";
	$rv .= "<tr class='ui_columns_heading'><td colspan='".scalar(@$heads)."'><b>$title</b></td></tr>\n" if $title;
	$rv .= "<tr class='ui_columns_heads'>";
	for my $i (0..$#$heads) { $rv .= "<td ".($tdtags->[$i] // '')."><b>$heads->[$i]</b></td>"; }
	return $rv."</tr>\n";
}
sub ui_columns_row {
	my ($cols, $tdtags) = @_;
	my $rv = "<tr class='ui_columns_row'>";
	for my $i (0..$#$cols) { $rv .= "<td ".($tdtags->[$i] // '').">".($cols->[$i] =~ /\S/ ? $cols->[$i] : '<br>')."</td>"; }
	return $rv."</tr>\n";
}
sub ui_columns_end { return "</table>\n"; }
sub ui_alert_box {
	my ($msg, $type) = @_;
	my %c = (success => 'DFF0D8', info => 'D9EDF7', warn => 'FCF8E3', danger => 'F2DEDE');
	return "<div class='alert' style='background:#$c{$type};padding:8px;margin:6px 0'>$msg</div>\n";
}
sub ui_link {
	my ($href, $text, $class, $tags) = @_;
	return "<a href=\"$href\" ".($tags // '').">$text</a>";
}
1;
