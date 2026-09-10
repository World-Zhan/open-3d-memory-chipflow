`timescale 1ns/1ps
module tb;
  supply1 vdd, iovdd;
  supply0 vss, iovss;
  reg in_value, out_value, core_value, enable, ext_enable, ext_value;
  wire in_core, out_pad, bi_core;
  tri bi_pad;
  assign bi_pad = ext_enable ? ext_value : 1'bz;
  sg13g2_IOPadIn dut_in(.pad(in_value),.p2c(in_core),.vdd(vdd),.vss(vss),.iovdd(iovdd),.iovss(iovss));
  sg13g2_IOPadOut16mA dut_out(.pad(out_pad),.c2p(out_value),.vdd(vdd),.vss(vss),.iovdd(iovdd),.iovss(iovss));
  sg13g2_IOPadInOut30mA dut_bi(.pad(bi_pad),.c2p(core_value),.p2c(bi_core),.c2p_en(enable),.vdd(vdd),.vss(vss),.iovdd(iovdd),.iovss(iovss));
  integer assertions=0, failures=0, i, j, k, l;
  reg expected;
  task check;
    input actual, wanted;
    input [255:0] label;
    begin
      assertions=assertions+1;
      if (actual !== wanted) begin
        failures=failures+1;
        $display("MISMATCH %0s actual=%b expected=%b",label,actual,wanted);
      end
    end
  endtask
  initial begin
    $dumpfile("/output/wave.vcd"); $dumpvars(0,tb);
    enable=0;ext_enable=0;ext_value=0;core_value=0;in_value=0;out_value=0;
    for(i=0;i<4;i=i+1) begin
      case(i) 0:begin in_value=0;out_value=0;end
              1:begin in_value=1;out_value=1;end
              2:begin in_value=1'bx;out_value=1'bx;end
              3:begin in_value=1'bz;out_value=1'bz;end endcase
      #1;check(in_core,in_value,"input four-state transfer");check(out_pad,out_value,"output four-state transfer");
    end
    for(i=0;i<2;i=i+1) for(j=0;j<2;j=j+1) for(k=0;k<2;k=k+1) for(l=0;l<2;l=l+1) begin
      enable=i;core_value=j;ext_enable=k;ext_value=l;
      if(i==0 && k==0) expected=1'bz;
      else if(i==0) expected=l;
      else if(k==0) expected=j;
      else if(j==l) expected=j;
      else expected=1'bx;
      #1;check(bi_pad,expected,"bidirectional resolved pad");check(bi_core,expected,"bidirectional receiver");
      $display("BIDIR en=%b core=%b ext_en=%b ext=%b pad=%b rx=%b expected=%b",enable,core_value,ext_enable,ext_value,bi_pad,bi_core,expected);
    end
    enable=1'bx;ext_enable=0;core_value=1;#1;
    check(bi_pad,1'bx,"unknown enable pad");check(bi_core,1'bx,"unknown enable receiver");
    $display("ASSERTIONS=%0d FAILURES=%0d",assertions,failures);
    if(failures!=0) $fatal(1,"OFFICIAL_IO_BEHAVIOR_FAIL");
    $display("OFFICIAL_IO_BEHAVIOR_PASS");$finish;
  end
endmodule
